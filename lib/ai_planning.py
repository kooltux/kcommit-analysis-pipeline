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
