"""Canonical records preserve assessment rules while removing physical chunk binding."""
import copy
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from lib import ai_canonical as canonical
from lib.ai_contract import digest, result_properties
from lib.ai_source import SourceIndex
from test_ai_import_sources import record as assessment
from test_ai_package_server import package, snapshots


@pytest.fixture
def context(package):
    source = SourceIndex(package['manifest'],
        lambda name: package['files']['ai_analysis_input/' + name])
    schemas = {role: json.loads(package['files']['ai_contract/schemas/' + role + '.json'])
               for role in canonical.ROLES + ('result',)}
    return source, schemas, assessment(SimpleNamespace(schema=schemas['result']))


def documents(context):
    source, schemas, item = context
    return {role: dict(run_id=source.manifest['run_id'], role=role,
                       results={sha: {key: copy.deepcopy(item[key])
                                      for key in result_properties(schemas[role])}
                                for sha in source.records})
            for role in canonical.ROLES}


def test_identity_uses_source_product_contracts_not_grouping(context):
    source, schemas, item = context
    commits = [source.record(sha) for sha in source.records]
    contracts = source.manifest['contract_assets']
    product = {'product': 'target'}
    original = copy.deepcopy((commits, contracts, product))
    identity = canonical.analysis_identity(commits, product, contracts)
    assert canonical.analysis_identity(list(reversed(commits)), product, contracts) == identity
    assert canonical.analysis_identity(commits, {'product': 'other'}, contracts) != identity
    changed = dict(contracts, extra='f' * 64)
    assert canonical.analysis_identity(commits, product, changed) != identity
    assert (commits, contracts, product) == original
    with pytest.raises(ValueError):
        canonical.analysis_identity(commits + commits[:1], product, contracts)


def test_grouped_assembly_and_schemas_have_no_chunk_metadata(context):
    source, schemas, item = context
    submitted = documents(context)
    before = copy.deepcopy(submitted)
    records = canonical.assemble_contributions(submitted, source, schemas, source.manifest['run_id'])
    assert submitted == before
    assert set(records) == set(source.records)
    for role in canonical.ROLES:
        schema = canonical.role_schema(schemas[role])
        Draft202012Validator(schema).validate(submitted[role])
        assert set(schema['required']) == {'run_id', 'role', 'results'}
        assert 'source_chunk' not in schema['properties']
    schema = canonical.record_schema(schemas['result'])
    for sha, value in records.items():
        assert value == dict(run_id=source.manifest['run_id'], commit=sha, assessment=item)
        Draft202012Validator(schema).validate(value)


@pytest.mark.parametrize('problem', ['fourth', 'chunk', 'coverage', 'unknown', 'field'])
def test_shared_assembly_rejects_invalid_contributions(context, problem):
    source, schemas, item = context
    submitted = documents(context)
    sha = next(iter(source.records))
    if problem == 'fourth':
        submitted['result'] = {}
    elif problem == 'chunk':
        submitted['analyst']['source_chunk'] = source.chunk_for(sha)
    elif problem == 'coverage':
        submitted['reviewer']['results'].pop(sha)
    elif problem == 'unknown':
        submitted['analyst']['results']['f' * 40] = submitted['analyst']['results'][sha]
    else:
        submitted['analyst']['results'][sha]['ai_is_bug_fix'] = 'FALSE'
    with pytest.raises(ValueError):
        canonical.assemble_contributions(submitted, source, schemas, source.manifest['run_id'])


def test_canonical_store_paths_receipts_replacement_and_run_isolation(context, tmp_path):
    source, schemas, item = context
    run_id = source.manifest['run_id']
    records = canonical.assemble_contributions(documents(context), source, schemas, run_id)
    root = tmp_path / 'results'
    store = canonical.CanonicalStore(root, source, schemas['result'], run_id)
    assert store.assessments() == {} and not root.exists()
    receipts = store.put_many(records)
    for sha in records:
        path = root / sha[:2] / sha[2:4] / (sha + '.json')
        assert path.read_bytes() == store.get(sha)
        assert receipts[sha] == digest(path.read_bytes())
    sha = next(iter(records))
    changed = copy.deepcopy(records[sha])
    changed['assessment']['ai_summary'] = 'Replacement assessment'
    store.put_many({sha: changed})
    expected = {key: value['assessment'] for key, value in records.items()}
    expected[sha] = changed['assessment']
    assert store.assessments() == expected
    other = canonical.CanonicalStore(root, source, schemas['result'], 'f' * 64)
    assert other.assessments() == {}
    assert not (root / 'runs').exists() and not (root / 'chunks').exists()


def test_all_records_validate_before_any_write(context, tmp_path):
    source, schemas, item = context
    run_id = source.manifest['run_id']
    records = canonical.assemble_contributions(documents(context), source, schemas, run_id)
    sha = sorted(records)[-1]
    records[sha]['commit'] = sorted(records)[0]
    root = tmp_path / 'absent'
    store = canonical.CanonicalStore(root, source, schemas['result'], run_id)
    with pytest.raises(ValueError):
        store.put_many(records)
    assert not root.exists()


@pytest.mark.parametrize('sha', ['../outside', 'a' * 39, 'A' * 40, None])
def test_unsafe_record_paths_are_rejected(sha):
    with pytest.raises(ValueError):
        canonical.record_path(sha)
