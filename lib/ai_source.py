"""Verified source identities and deterministic selections, independent of storage."""
import copy
import json
import re

from lib.ai_contract import AssessmentValidationError, NAME, SHA, digest, validate_chunk


def _fail(message, field, commit=None):
    details = {'field': field}
    if commit is not None:
        details['commit'] = commit
    raise AssessmentValidationError(message, **details) from None


def index_source_commits(commits):
    """Index source identities without changing record order or content."""
    if not isinstance(commits, list):
        _fail('Invalid source commit collection', 'commits')
    records = {}
    for item in commits:
        sha = item.get('commit') if isinstance(item, dict) else None
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            _fail('Invalid source commit SHA', 'commit')
        if sha in records:
            _fail('Duplicate source SHA across the AI source set', 'commit', sha)
        records[sha] = item
    return records


def _decode_source(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-JSON numeric constant')
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError):
        _fail('Invalid source JSON', 'source_chunk')


class SourceIndex:
    """Read each manifest-listed chunk once through a caller-supplied byte reader."""

    def __init__(self, manifest, read_chunk, on_chunk=None):
        if not isinstance(manifest, dict) or not callable(read_chunk):
            _fail('Invalid source index inputs', 'manifest')
        self.manifest = copy.deepcopy(manifest)
        names = self.manifest.get('chunks')
        if not isinstance(names, dict) or not names:
            _fail('Source package requires source chunks', 'chunks')
        if any(not isinstance(name, str) or not NAME.fullmatch(name) for name in names):
            _fail('Invalid source chunk path', 'source_chunk')
        for field in ('run_id', 'input_schema_checksum', 'output_schema_checksum'):
            value = self.manifest.get(field)
            if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
                _fail('Invalid source identity: ' + field, field)
        for field in ('total_commits', 'total_chunks'):
            value = self.manifest.get(field)
            if type(value) is not int or value < 0:
                _fail('Invalid source count: ' + field, field)
        self.chunks, self.raw, self.by_sha, self.records, self.checksums = {}, {}, {}, {}, {}
        for number, name in enumerate(sorted(names), 1):
            try:
                data = read_chunk(name)
            except OSError:
                _fail('Cannot read source chunk: ' + name, 'source_chunk')
            if not isinstance(data, bytes) or digest(data) != names[name]:
                _fail('Source chunk checksum mismatch: ' + name, 'source_chunk')
            chunk = _decode_source(data)
            try:
                validate_chunk(chunk, self.manifest['input_schema_checksum'],
                               self.manifest['output_schema_checksum'], self.manifest['run_id'], name)
            except ValueError as exc:
                _fail(str(exc), 'source_chunk')
            for sha, item in index_source_commits(chunk['commits']).items():
                if sha in self.by_sha:
                    _fail('Duplicate source SHA across chunks: ' + sha, 'commit', sha)
                self.by_sha[sha], self.records[sha] = name, item
            self.chunks[name], self.raw[name], self.checksums[name] = chunk, data, names[name]
            if on_chunk is not None:
                on_chunk(number, len(names), name)
        if len(self.chunks) != self.manifest['total_chunks']:
            _fail('Source package total chunk mismatch', 'total_chunks')
        if len(self.records) != self.manifest['total_commits']:
            _fail('Source package total commit mismatch', 'total_commits')

    def chunk_for(self, sha):
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            _fail('Unknown result SHA', 'results')
        if sha not in self.by_sha:
            _fail('Unknown result SHA: ' + sha, 'results', sha)
        return self.by_sha[sha]

    def select(self, shas):
        """Return sorted, unique, source-bound commit identities, including empty selections."""
        if not isinstance(shas, (list, tuple)):
            _fail('Source selection must be a list or tuple', 'results')
        for sha in shas:
            self.chunk_for(sha)
        if len(set(shas)) != len(shas):
            _fail('Duplicate commit in source selection', 'results')
        return tuple(sorted(shas))

    def record(self, sha):
        self.chunk_for(sha)
        return copy.deepcopy(self.records[sha])

    def context(self, name):
        if not isinstance(name, str) or name not in self.chunks:
            _fail('Unknown source chunk', 'source_chunk')
        return copy.deepcopy(self.chunks[name])
