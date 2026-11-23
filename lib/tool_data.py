"""Read-only artifact assembly and manual selections (v21.7.0)."""
from copy import deepcopy
import json
from pathlib import Path
import re

from lib.commit_sets import NAMES, Unavailable, ids, load_json, read_sets_from_dirs
from lib.config import apply_override, load_config
from lib.gitutils import run_git


def configuration(args):
    cfg = load_config(args.config)
    if args.override:
        apply_override(cfg, args.override)
    if args.repo:
        cfg.setdefault('kernel', {})['source_dir'] = str(Path(args.repo).resolve())
    return cfg


class Dataset:
    def __init__(self, cfg):
        self.cfg, self.artifacts, self.records, self.lists = cfg, {}, {}, {}
        paths = cfg['paths']
        self.sets, self.errors, self.order = read_sets_from_dirs(
            paths['cache_dir'], paths['output_dir'], self.artifacts)
        self.warnings = []
        rejected = Path(paths['cache_dir']) / 'filtered_commits.json'
        if rejected.is_file():
            try:
                rows = load_json(str(rejected))
                members = set(ids(str(rejected), rows))
                if 'prefilter_rejected' not in self.sets or members != self.sets['prefilter_rejected']:
                    raise ValueError('Prefilter drops do not match the available all-related partition')
                self.artifacts['prefilter_rejected'] = rows
            except (OSError, ValueError) as exc:
                self.warnings.append(str(exc))
        for name in ('all', 'related', 'prefilter_rejected', 'scored', 'relevant', 'below_threshold'):
            for row in self.artifacts.get(name, []):
                collision = {'sets', 'lists', 'ai'}.intersection(row)
                if collision:
                    raise ValueError('Reserved query field collision: ' + ', '.join(sorted(collision)))
                self.records.setdefault(row['commit'], {}).update(deepcopy(row))
        from lib.ai_import_store import load_report_results
        self.ai = load_report_results(paths['output_dir'])

    def resolve(self, token):
        if not re.fullmatch(r'[0-9a-fA-F]{7,40}', token):
            raise ValueError('Expected a 7-40 hexadecimal commit ID: ' + token)
        token = token.lower()
        if len(token) == 40 and token in self.records:
            return token
        sha = run_git(self.cfg, ['rev-parse', '--verify', '--end-of-options', token + '^{commit}']).strip()
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('Git did not resolve a full commit ID: ' + token)
        return sha

    def read_list(self, path):
        values = []
        for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
            text = line.partition('#')[0].strip()
            if text:
                try:
                    values.append(self.resolve(text.split()[0]))
                except (ValueError, RuntimeError) as exc:
                    raise ValueError('%s:%d: %s' % (path, number, exc)) from exc
        return list(dict.fromkeys(values))

    def add_lists(self, specs):
        for spec in specs:
            name, separator, path = spec.partition('=')
            if not separator or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) or not path:
                raise ValueError('--list requires NAME=FILE with an identifier NAME')
            if name in self.lists:
                raise ValueError('Duplicate list name: ' + name)
            self.lists[name] = set(self.read_list(path))

    def record(self, sha):
        if sha not in self.records:
            text = run_git(self.cfg, ['show', '--no-patch', '--format=%H%x00%s%x00%B', sha, '--'])
            parts = text.split('\x00', 2)
            if len(parts) != 3 or parts[0] != sha:
                raise ValueError('Cannot read commit metadata: ' + sha)
            self.records[sha] = dict(commit=sha, subject=parts[1], body=parts[2].rstrip('\n'))
        row = deepcopy(self.records[sha])
        row['sets'] = {name: sha in self.sets[name] if name in self.sets else None for name in NAMES}
        row['lists'] = {name: sha in members for name, members in self.lists.items()}
        row['ai'] = deepcopy(self.ai.get(sha))
        return row

    def population(self, name, path=None):
        if path:
            members = self.read_list(path)
        else:
            if 'all' not in self.sets or name not in self.sets:
                raise Unavailable('Unavailable population %s: %s' % (name, self.errors.get(name, self.errors.get('all', 'unknown'))))
            members = [sha for sha in self.order if sha in self.sets[name]]
        return [self.record(sha) for sha in members]

    def summary(self):
        return dict(sets=[dict(name=name, count=len(self.sets[name]) if name in self.sets else None,
                              error=self.errors.get(name)) for name in NAMES],
                    ai_imported=len(self.ai), warnings=self.warnings, cache_dir=self.cfg['paths']['cache_dir'],
                    output_dir=self.cfg['paths']['output_dir'])


def fields(rows):
    catalog = {}
    for row in rows:
        seen = {}
        def walk(value, path):
            kind = 'null' if value is None else 'boolean' if type(value) is bool else 'number' if type(value) in (int, float) else 'object' if isinstance(value, dict) else 'array' if isinstance(value, list) else 'string'
            if path:
                seen.setdefault(path, set()).add(kind)
            if isinstance(value, dict):
                for key, item in value.items():
                    part = key if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) else json.dumps(key)
                    walk(item, path + '.' + part if path else part)
            elif isinstance(value, list):
                for item in value:
                    walk(item, path + '[]')
        walk(row, '')
        for path, kinds in seen.items():
            entry = catalog.setdefault(path, dict(path=path, types=set(), present=0, non_null=0))
            entry['types'].update(kinds)
            entry['present'] += 1
            entry['non_null'] += bool(kinds - {'null'})
    return [dict(entry, types=sorted(entry['types']), records=len(rows), missing=len(rows) - entry['present'],
                 example='--project ' + json.dumps(entry['path'])) for _, entry in sorted(catalog.items())]
