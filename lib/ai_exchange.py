"""Validated AI exchange readers, deterministic deduplication and progress."""
import json
import os
from pathlib import Path
import sys
import time
import zipfile

from lib.ai_contract import NAME, SHA, digest, validate_chunk, validate_result


class Progress:
    def __init__(self, label):
        self.label = label
        self.started = self.last = time.monotonic()

    def say(self, message, force=True):
        now = time.monotonic()
        if force or now - self.last >= 1:
            print(f'[{self.label} {now - self.started:.1f}s] {message}',
                  file=sys.stderr, flush=True)
            self.last = now


def decode(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f'Duplicate JSON key: {key}')
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique)


def discover(inputs, suffix, progress):
    found = set()
    progress.say(f'Discovering {suffix} files')
    for raw in inputs:
        path = Path(raw).absolute()
        if path.is_symlink():
            raise ValueError(f'Symlink input is not supported: {path}')
        if path.is_dir():
            for base, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if not Path(base, d).is_symlink())
                for name in files:
                    item = Path(base, name)
                    if item.suffix.lower() == suffix and not item.is_symlink():
                        found.add(item)
                progress.say(f'Discovery: {len(found)} files; scanning {base}', False)
        elif path.is_file() and path.suffix.lower() == suffix:
            found.add(path)
        else:
            raise ValueError(f'Expected a {suffix} file or directory: {path}')
    if not found:
        raise ValueError(f'No {suffix} files found')
    progress.say(f'Discovered {len(found)} files')
    return sorted(found, key=lambda p: p.as_posix())


class Assessments:
    def __init__(self, progress):
        self.progress = progress
        self.results, self.origins = {}, {}
        self.identical = self.conflicts = 0

    def add(self, sha, item, origin):
        if sha not in self.results:
            self.results[sha], self.origins[sha] = item, origin
        elif self.results[sha] == item:
            self.identical += 1
        else:
            self.conflicts += 1
            differences = {key: {'retained': self.results[sha].get(key),
                                 'rejected': item.get(key)}
                           for key in sorted(set(item) | set(self.results[sha]))
                           if self.results[sha].get(key) != item.get(key)}
            self.progress.say(f'WARNING conflicting duplicate {sha}: retained '
                              f'{self.origins[sha]}; rejected {origin}; fields='
                              + json.dumps(differences, ensure_ascii=True, sort_keys=True))

    def summary(self):
        return (f'{len(self.results)} unique commits; {self.identical} identical duplicates '
                f'skipped; {self.conflicts} conflicting duplicates rejected')


class WorkPackage:
    def __init__(self, cfg, progress):
        self.root = Path(cfg['paths']['output_dir'])
        progress.say(f'Validating source package: {self.root}')
        self.manifest_bytes = (self.root / 'ai_analysis_bundle_manifest.json').read_bytes()
        self.manifest = decode(self.manifest_bytes)
        for filename, field in [('ai_analysis_input_schema.json', 'input_schema_checksum'),
                                ('ai_analysis_result_schema.json', 'output_schema_checksum'),
                                ('ai_analysis_prompt.md', 'prompt_checksum')]:
            data = (self.root / filename).read_bytes()
            if digest(data) != self.manifest[field]:
                raise ValueError('Local AI contract checksum mismatch: ' + filename)
            if field == 'output_schema_checksum':
                self.schema = decode(data)
        self.chunks, self.raw, self.by_sha = {}, {}, {}
        for index, (name, expected) in enumerate(sorted(self.manifest['chunks'].items()), 1):
            if not NAME.fullmatch(name):
                raise ValueError('Invalid chunk path in AI manifest')
            data = (self.root / 'ai_analysis_input' / name).read_bytes()
            if digest(data) != expected:
                raise ValueError('Local source chunk checksum mismatch: ' + name)
            chunk = decode(data)
            validate_chunk(chunk, self.manifest['input_schema_checksum'],
                           self.manifest['output_schema_checksum'], self.manifest['run_id'], name)
            self.chunks[name], self.raw[name] = chunk, data
            for item in chunk['commits']:
                sha = item['commit']
                if sha in self.by_sha:
                    raise ValueError('Duplicate source SHA across chunks: ' + sha)
                self.by_sha[sha] = name
            progress.say(f'Validated source chunk {index}/{len(self.manifest["chunks"])}: {name}', False)
        progress.say(f'Source run {self.manifest["run_id"]}: '
                     f'{len(self.chunks)} chunks, {len(self.by_sha)} commits')

    def envelope(self, name, results):
        chunk = self.chunks[name]
        return dict(schema_version='1.0', run_id=self.manifest['run_id'], source_chunk=name,
                    input_checksum=digest(self.raw[name]),
                    input_schema_checksum=self.manifest['input_schema_checksum'],
                    output_schema_checksum=self.manifest['output_schema_checksum'],
                    total_commits=chunk['total_commits'], analyzed_commits=len(results),
                    analysis_status='complete' if len(results) == chunk['total_commits'] else 'partial',
                    results=results)

    def validate_item(self, sha, item):
        if not isinstance(sha, str) or not SHA.fullmatch(sha) or sha not in self.by_sha:
            raise ValueError('Unknown result SHA: ' + str(sha))
        name = self.by_sha[sha]
        value = self.envelope(name, {sha: item})
        validate_result(value, self.chunks[name], self.schema, digest(self.raw[name]))

    def accept_document(self, value, origin, accepted):
        if not isinstance(value, dict):
            raise ValueError('Result document must be an object')
        if 'source_chunk' in value:
            name = value['source_chunk']
            if not isinstance(name, str) or name not in self.chunks:
                raise ValueError('Unknown source chunk')
            validate_result(value, self.chunks[name], self.schema, digest(self.raw[name]))
        else:
            keys = {'schema_version', 'run_id', 'input_schema_checksum',
                    'output_schema_checksum', 'results'}
            if set(value) != keys or not isinstance(value['results'], dict):
                raise ValueError('Invalid collection envelope')
            for key in keys - {'results'}:
                expected = '1.0' if key == 'schema_version' else self.manifest[key]
                if value[key] != expected:
                    raise ValueError('Collection identity mismatch: ' + key)
        for sha, item in value['results'].items():
            self.validate_item(sha, item)
            accepted.add(sha, item, origin)
            accepted.progress.say(f'Processing {origin}: {len(accepted.results)} unique commits', False)


def read_assessments(package, source, progress):
    accepted = Assessments(progress)
    path = Path(source)
    if path.is_file() and zipfile.is_zipfile(path):
        progress.say(f'Validating server export: {path}')
        with zipfile.ZipFile(path) as bundle:
            names = bundle.namelist()
            expected = set(package.chunks)
            allowed = ({'ai_analysis_bundle_manifest.json'} |
                       {'ai_analysis_input/' + n for n in expected} |
                       {'results/' + n for n in expected})
            if len(names) != len(set(names)) or set(names) - allowed:
                raise ValueError('Unknown or duplicate bundle member')
            if bundle.read('ai_analysis_bundle_manifest.json') != package.manifest_bytes:
                raise ValueError('Returned bundle belongs to another AI run')
            for index, name in enumerate(sorted(expected), 1):
                member = 'ai_analysis_input/' + name
                if member not in names:
                    raise ValueError('Missing source chunks in result bundle')
                if bundle.read(member) != package.raw[name]:
                    raise ValueError('Returned source chunk checksum mismatch')
                progress.say(f'Validated export chunk {index}/{len(expected)}: {name}', False)
            files = sorted(n for n in names if n.startswith('results/'))
            for index, name in enumerate(files, 1):
                value = decode(bundle.read(name))
                if not isinstance(value, dict) or value.get('source_chunk') != name[len('results/'):]:
                    raise ValueError('Result identity mismatch: source_chunk')
                package.accept_document(value, f'{path}!{name}', accepted)
                progress.say(f'Read result {index}/{len(files)}: {name}', index in (1, len(files)))
    else:
        files = discover([path], '.json', progress)
        for index, name in enumerate(files, 1):
            try:
                package.accept_document(decode(name.read_bytes()), str(name), accepted)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f'{name}: {exc}') from exc
            progress.say(f'Read result {index}/{len(files)}: {name}', index in (1, len(files)))
    progress.say(f'Validated input: {accepted.summary()}')
    return accepted
