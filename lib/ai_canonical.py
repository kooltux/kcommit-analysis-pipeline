"""Canonical analysis identity, chunk-independent contributions and per-commit records."""
import copy
import os
import re
import threading

from .ai_contract import AssessmentValidationError, digest, result_properties, validate_assessment
from .ai_result_store import _atomic_bytes, _decode, _encode
from .ai_source import index_source_commits

ROLES = ('analyst', 'cve', 'reviewer')


def analysis_identity(commits, product_map, contract_assets):
    """Hash source/product/contracts, never transport grouping or planning options."""
    indexed = index_source_commits(commits)
    if not isinstance(product_map, dict) or not isinstance(contract_assets, dict) or not contract_assets:
        raise ValueError('Invalid analysis identity inputs')
    for name, checksum in contract_assets.items():
        if (not isinstance(name, str) or not isinstance(checksum, str)
                or not re.fullmatch(r'[0-9a-f]{64}', checksum)):
            raise ValueError('Invalid analysis contract identity')
    return digest(_encode(dict(commits=[indexed[sha] for sha in sorted(indexed)],
                               product=product_map, contracts=contract_assets)))


def record_path(sha):
    if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise AssessmentValidationError('Invalid result SHA', field='commit')
    return '/'.join((sha[:2], sha[2:4], sha + '.json'))


def role_schema(schema):
    """Retain assessment definitions while removing physical source-chunk binding."""
    value = copy.deepcopy(schema)
    value['required'] = ['run_id', 'role', 'results']
    value['properties'] = {key: value['properties'][key] for key in value['required']}
    value['additionalProperties'] = False
    value['description'] = 'Grouped source-bound role findings independent of delivery grouping.'
    return value


def record_schema(schema):
    properties = copy.deepcopy(result_properties(schema))
    value = dict(type='object', additionalProperties=False,
                required=['run_id', 'commit', 'assessment'], properties={
                    'run_id': dict(type='string', pattern='^[0-9a-f]{64}$'),
                    'commit': dict(type='string', pattern='^[0-9a-f]{40}$'),
                    'assessment': dict(type='object', additionalProperties=False,
                                       required=list(properties), properties=properties)})
    if '$defs' in schema:
        value['$defs'] = copy.deepcopy(schema['$defs'])
    return value


def validate_record(value, source, schema, run_id, sha=None):
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{64}', run_id):
        raise ValueError('Invalid trusted analysis identity')
    if not isinstance(value, dict) or set(value) != {'run_id', 'commit', 'assessment'}:
        raise AssessmentValidationError('Invalid canonical result envelope', field='assessment')
    if value['run_id'] != run_id:
        raise AssessmentValidationError('Result run identity mismatch', field='run_id')
    record_path(value['commit'])
    if sha is not None and value['commit'] != sha:
        raise AssessmentValidationError('Result filename identity mismatch', field='commit')
    source.chunk_for(value['commit'])
    validate_assessment(value['commit'], value['assessment'], schema)
    return True


def validate_role_document(role, value, source, schemas, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{64}', run_id):
        raise ValueError('Invalid trusted analysis identity')
    if role not in ROLES:
        raise AssessmentValidationError('Unknown contribution role', field='role')
    if (not isinstance(value, dict) or set(value) != {'run_id', 'role', 'results'}
            or value['run_id'] != run_id or value['role'] != role
            or not isinstance(value['results'], dict)):
        raise AssessmentValidationError('Invalid canonical role document', field='results')
    for sha, assessment in value['results'].items():
        source.chunk_for(sha)
        try:
            validate_assessment(sha, assessment, schemas[role])
        except AssessmentValidationError as exc:
            exc.details.setdefault('role', role)
            raise
    return True


def assemble_contributions(documents, source, schemas, run_id):
    """Shared validation/submission gate: assemble three roles, never store here."""
    if not isinstance(documents, dict) or set(documents) != set(ROLES):
        raise AssessmentValidationError('Exactly three role documents are required', field='documents')
    for role in ROLES:
        validate_role_document(role, documents[role], source, schemas, run_id)
    coverage = set(documents['analyst']['results'])
    if any(set(documents[role]['results']) != coverage for role in ROLES):
        raise AssessmentValidationError('Role coverage mismatch', field='results')
    records = {}
    for sha in sorted(coverage):
        assessment = {}
        for role in ROLES:
            fields = documents[role]['results'][sha]
            if set(fields) & set(assessment):
                raise AssessmentValidationError('Overlapping role fields', commit=sha, field='results')
            assessment.update(copy.deepcopy(fields))
        record = dict(run_id=run_id, commit=sha, assessment=assessment)
        validate_record(record, source, schemas['result'], run_id)
        records[sha] = record
    return records


class CanonicalStore:
    """Publish independent records atomically per SHA; one writer instance per root.

    Files from other runs are not current findings. Their fixed SHA locations may
    be replaced by a valid current-run submission. Cross-record rollback and
    interprocess writer locking are not provided.
    """

    def __init__(self, root, source, schema, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{64}', run_id):
            raise ValueError('Invalid trusted analysis identity')
        self.root = os.path.abspath(root)
        self.source, self.schema, self.run_id = source, copy.deepcopy(schema), run_id
        self._lock = threading.RLock()

    def get(self, sha):
        relative = record_path(sha)
        self.source.chunk_for(sha)
        try:
            with open(os.path.join(self.root, relative), 'rb') as stream:
                data = stream.read()
        except FileNotFoundError:
            return None
        value = _decode(data)
        if isinstance(value, dict) and value.get('run_id') != self.run_id:
            return None
        validate_record(value, self.source, self.schema, self.run_id, sha)
        return _encode(value)

    def put_many(self, records):
        """Prevalidate every supplied record before creating directories or writing."""
        if not isinstance(records, dict):
            raise ValueError('Canonical records must be keyed by SHA')
        prepared = {}
        for sha, value in records.items():
            record_path(sha)
            value = _decode(_encode(value))
            validate_record(value, self.source, self.schema, self.run_id, sha)
            prepared[sha] = _encode(value)
        with self._lock:
            for sha in sorted(prepared):
                _atomic_bytes(os.path.join(self.root, record_path(sha)), prepared[sha])
        return {sha: digest(prepared[sha]) for sha in sorted(prepared)}

    def assessments(self):
        results = {}
        for sha in sorted(self.source.records):
            data = self.get(sha)
            if data is not None:
                results[sha] = _decode(data)['assessment']
        return results
