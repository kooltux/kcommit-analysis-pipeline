"""Deterministic byte-bounded source plans with a bounded in-memory cache."""
from collections import OrderedDict
import copy
import re
import threading

from .ai_contract import digest
from .ai_result_store import _encode

DEFAULTS = {'max_commits': 100, 'max_bytes': 1048576, 'cache_entries': 32}


def planning_defaults(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Invalid AI planning options')
    options = dict(DEFAULTS, **value)
    if any(type(number) is not int or number <= 0 for number in options.values()):
        raise ValueError('AI planning limits must be positive integers')
    return options


def source_document(source, run_id, shas):
    selected = source.select(shas)
    return dict(run_id=run_id, commits=[source.record(sha) for sha in selected])


class PlanCache:
    """Planning affects delivery only, never canonical record identity or paths.

    max_bytes bounds exact encoded source-document bytes, not model tokens or
    the combined prompt/output context. Cached values are defensive snapshots.
    """

    def __init__(self, source, run_id, defaults=None):
        if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{64}', run_id):
            raise ValueError('Invalid planning analysis identity')
        self.source, self.run_id = source, run_id
        self.defaults = planning_defaults(defaults)
        self._cache = OrderedDict()
        self._lock = threading.RLock()

    def cached(self, plan_id):
        with self._lock:
            value = self._cache.get(plan_id)
            if value is not None:
                self._cache.move_to_end(plan_id)
            return copy.deepcopy(value)

    def get(self, request=None):
        request = {} if request is None else request
        if not isinstance(request, dict) or set(request) - {'max_commits', 'max_bytes', 'commits'}:
            raise ValueError('Invalid plan request')
        limits = {key: request.get(key, self.defaults[key]) for key in ('max_commits', 'max_bytes')}
        if any(type(value) is not int or value <= 0 for value in limits.values()):
            raise ValueError('Plan limits must be positive integers')
        shas = self.source.select(request.get('commits', list(self.source.records)))
        parameters = dict(limits, commits=list(shas))
        plan_id = digest(_encode(dict(run_id=self.run_id, parameters=parameters)))
        with self._lock:
            previous = self.cached(plan_id)
            if previous is not None:
                return previous
            groups, current = [], []
            def size(values):
                return len(_encode(source_document(self.source, self.run_id, values)))
            def finish(values):
                return dict(group_id=digest(_encode(dict(run_id=self.run_id, commits=values))),
                            commits=list(values), input_bytes=size(values))
            for sha in shas:
                candidate = current + [sha]
                if len(candidate) > limits['max_commits'] or size(candidate) > limits['max_bytes']:
                    if current:
                        groups.append(finish(current))
                    current = [sha]
                    if size(current) > limits['max_bytes']:
                        raise ValueError('A source commit exceeds the plan byte limit: ' + sha)
                else:
                    current = candidate
            if current:
                groups.append(finish(current))
            result = dict(run_id=self.run_id, plan_id=plan_id, parameters=parameters, groups=groups)
            self._cache[plan_id] = result
            while len(self._cache) > self.defaults['cache_entries']:
                self._cache.popitem(last=False)
            return copy.deepcopy(result)


class GroupPlanner(PlanCache):
    """AI planning with durable group membership, independent of the plan cache."""

    def __init__(self, source, run_id, root, defaults=None):
        super().__init__(source, run_id, defaults)
        from pathlib import Path
        self.group_directory = Path(root) / 'groups' / run_id

    @staticmethod
    def query_options(query):
        from urllib.parse import parse_qsl
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=3)
        allowed = {'max_commits_per_group', 'max_bytes_per_group', 'max_groups'}
        options = {}
        for name, value in pairs:
            if name not in allowed or name in options or not re.fullmatch(r'[0-9]+', value):
                raise ValueError('Invalid planning query parameter')
            number = int(value)
            if number < 1:
                raise ValueError('Planning limits must be positive integers')
            options[name] = number
        return options

    def plan(self, options=None):
        options = {} if options is None else options
        allowed = {'max_commits_per_group', 'max_bytes_per_group', 'max_groups'}
        if (not isinstance(options, dict) or set(options) - allowed
                or any(type(value) is not int or value < 1 for value in options.values())):
            raise ValueError('Invalid group planning options')
        limits = {
            'max_commits': options.get('max_commits_per_group', self.defaults['max_commits']),
            'max_bytes': options.get('max_bytes_per_group', self.defaults['max_bytes']),
        }
        complete = super().get(limits)
        parameters = dict(max_commits_per_group=limits['max_commits'],
                          max_bytes_per_group=limits['max_bytes'],
                          max_groups=options.get('max_groups'))
        groups = complete['groups'][:options.get('max_groups')]
        public = []
        from .ai_result_store import _atomic_bytes
        for group in groups:
            definition = dict(run_id=self.run_id, commits=group['commits'])
            _atomic_bytes(str(self.group_directory / (group['group_id'] + '.json')),
                          _encode(definition))
            public.append(dict(group_id=group['group_id'],
                               commit_count=len(group['commits']), input_bytes=group['input_bytes']))
        return dict(run_id=self.run_id,
                    plan_id=digest(_encode(dict(run_id=self.run_id, parameters=parameters))),
                    parameters=parameters, total_groups=len(complete['groups']),
                    returned_groups=len(public), limited=len(public) < len(complete['groups']),
                    groups=public)

    def group(self, group_id):
        from .ai_result_store import _decode
        if not isinstance(group_id, str) or not re.fullmatch(r'[0-9a-f]{64}', group_id):
            raise KeyError('Unknown group')
        try:
            data = (self.group_directory / (group_id + '.json')).read_bytes()
        except FileNotFoundError:
            raise KeyError('Unknown group') from None
        definition = _decode(data)
        if (not isinstance(definition, dict) or set(definition) != {'run_id', 'commits'}
                or definition['run_id'] != self.run_id or digest(_encode(definition)) != group_id
                or not isinstance(definition['commits'], list) or not definition['commits']):
            raise ValueError('Invalid persisted group definition')
        return source_document(self.source, self.run_id, definition['commits'])
