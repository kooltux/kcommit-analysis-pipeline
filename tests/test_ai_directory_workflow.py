"""Directory snapshots and preservation gates for the forward-only AI contract."""
import copy
from pathlib import Path
import shutil

import pytest

from lib.ai_assets import load_contract
from lib.ai_contract import result_properties
from lib.ai_workflow import validate_workflow

SAMPLES = Path(__file__).resolve().parents[1] / 'configs' / 'ai'


@pytest.fixture
def selected(tmp_path):
    shutil.copytree(SAMPLES / 'prompts', tmp_path / 'ai' / 'prompts')
    shutil.copytree(SAMPLES / 'schemas', tmp_path / 'ai' / 'schemas')
    return {'ai': {}, '_meta': {'initial_config_dir': str(tmp_path)}}


def test_snapshots_are_exact_and_detached(selected, tmp_path):
    contract = load_contract(selected)
    assert len(contract['files']) == 9
    path = tmp_path / 'ai/prompts/analyst.md'
    before = path.read_bytes()
    assert contract['files']['prompts/analyst.md'] == before
    path.write_bytes(before + b'\nChanged')
    assert contract['files']['prompts/analyst.md'] == before
    assert load_contract(selected)['checksums'] != contract['checksums']


@pytest.mark.parametrize('path', [
    'prompts/analyst.md', 'prompts/cve.md', 'prompts/reviewer.md', 'prompts/assembler.md',
    'schemas/input.json', 'schemas/analyst.json', 'schemas/cve.json',
    'schemas/reviewer.json', 'schemas/result.json',
])
def test_missing_required_asset_is_not_replaced(selected, tmp_path, path):
    (tmp_path / 'ai' / path).unlink()
    with pytest.raises(ValueError):
        load_contract(selected)


@pytest.mark.parametrize('key', ['prompt_path', 'result_schema_path'])
def test_removed_file_settings_are_rejected(selected, key):
    selected['ai'][key] = 'unused'
    with pytest.raises(ValueError, match='Removed AI settings'):
        load_contract(selected)


@pytest.fixture
def assessment(selected):
    schemas = load_contract(selected)['schemas']
    chunk = dict(run_id='b' * 64, source_chunk='batch_001/001.json',
                 input_schema_checksum='c' * 64, output_schema_checksum='d' * 64,
                 total_commits=1, commits=[{'commit': 'a' * 40}])
    record = {}
    for key, spec in result_properties(schemas['result']).items():
        kind = spec['type']
        record[key] = (None if isinstance(kind, list) else False if kind == 'boolean'
                       else [] if kind == 'array' else spec.get('enum', ['evidence'])[0])
    record.update(rv_agreement='agree', ai_risks_if_not_backported=['none'])
    result = dict(schema_version='1.0', run_id=chunk['run_id'],
                  source_chunk=chunk['source_chunk'], input_checksum='e' * 64,
                  input_schema_checksum=chunk['input_schema_checksum'],
                  output_schema_checksum=chunk['output_schema_checksum'],
                  total_commits=1, analyzed_commits=1, analysis_status='complete',
                  results={'a' * 40: record})
    documents = {'result': result}
    for role in ('analyst', 'cve', 'reviewer'):
        fields = result_properties(schemas[role])
        contribution = {key: copy.deepcopy(record[key]) for key in fields}
        documents[role] = dict(result, role=role, results={'a' * 40: contribution})
    return documents, chunk, schemas


def check(assessment):
    documents, chunk, schemas = assessment
    return validate_workflow(documents, chunk, schemas, 'e' * 64)


def test_workflow_preserves_specialists_and_review(assessment):
    before = copy.deepcopy(assessment)
    assert check(assessment)
    assert assessment == before
    assessment[0]['result']['results']['a' * 40]['ai_summary'] = 'Rewritten'
    with pytest.raises(ValueError, match='Assembly changed'):
        check(assessment)


@pytest.mark.parametrize('role', ['analyst', 'cve', 'reviewer', 'result'])
def test_workflow_identity_is_checked_for_every_document(assessment, role):
    assessment[0][role]['input_checksum'] = 'f' * 64
    with pytest.raises(ValueError, match='identity'):
        check(assessment)


def test_reviewer_cannot_cover_missing_specialists(assessment):
    assessment[0]['analyst'].update(results={}, analyzed_commits=0, analysis_status='partial')
    with pytest.raises(ValueError, match='specialist contributions'):
        check(assessment)


def test_final_cannot_cover_unreviewed_commits(assessment):
    assessment[0]['reviewer'].update(results={}, analyzed_commits=0, analysis_status='partial')
    with pytest.raises(ValueError, match='reviewed contribution'):
        check(assessment)
