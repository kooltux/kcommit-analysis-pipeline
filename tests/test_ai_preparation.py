"""The next Stage 08 package engine uses selected snapshots, without file writes."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError

from lib.ai_assets import load_contract
from lib.ai_contract import digest
from lib.ai_preparation import build_package
from lib.manifest import VERSION

SAMPLES = Path(__file__).resolve().parents[1] / 'configs' / 'ai'
ASSETS = ['prompts/' + role + '.md' for role in ('analyst', 'cve', 'reviewer', 'assembler')]
ASSETS += ['schemas/' + role + '.json' for role in ('input', 'analyst', 'cve', 'reviewer', 'result')]


@pytest.fixture
def snapshots():
    return load_contract({'ai': {'prompts_dir': str(SAMPLES / 'prompts'),
                                 'schemas_dir': str(SAMPLES / 'schemas')}})['files']


def sources(count):
    return [{'commit': f'{index:040x}', 'subject': 'Fix', 'score': 100} for index in range(count)]


def build(snapshots, count=5, **options):
    return build_package(sources(count), {}, snapshots, VERSION, **options)


def test_package_preserves_exact_contract_bytes_and_sources(snapshots):
    before = copy.deepcopy(snapshots)
    package = build(snapshots, chunk_size=2, batch_size=2)
    manifest, files = package['manifest'], package['files']
    assert manifest['total_chunks'] == 3 and manifest['total_batches'] == 2
    assert list(manifest['chunks']) == ['batch_001/001.json', 'batch_001/002.json', 'batch_002/003.json']
    for name, data in snapshots.items():
        assert files['ai_contract/' + name] == data
        assert manifest['contract_assets'][name] == digest(data)
    assert files['ai_analysis_input_schema.json'] == snapshots['schemas/input.json']
    assert files['ai_analysis_result_schema.json'] == snapshots['schemas/result.json']
    for name, checksum in manifest['chunks'].items():
        data = files['ai_analysis_input/' + name]
        assert checksum == digest(data)
        assert all('score' not in item for item in json.loads(data)['commits'])
    assert json.loads(files['ai_analysis_bundle_manifest.json']) == manifest
    assert snapshots == before
    assert build(snapshots, chunk_size=2, batch_size=2) == package


@pytest.mark.parametrize('name', ASSETS)
def test_every_selected_asset_changes_identity(snapshots, name):
    original = build(snapshots)['manifest']['run_id']
    snapshots[name] += b'\n'
    assert build(snapshots)['manifest']['run_id'] != original


def test_selected_input_constraints_are_applied(snapshots):
    schema = json.loads(snapshots['schemas/input.json'])
    schema['properties']['commits']['items']['properties']['subject']['const'] = 'Required text'
    snapshots['schemas/input.json'] = json.dumps(schema).encode()
    with pytest.raises(ValidationError):
        build(snapshots)


def test_duplicate_shas_rejected_even_across_chunks(snapshots):
    with pytest.raises(ValueError, match='Duplicate source SHA'):
        build_package(sources(1) * 2, {}, snapshots, VERSION, chunk_size=1)


def test_empty_source_has_one_valid_empty_chunk(snapshots):
    package = build(snapshots, count=0)
    manifest = package['manifest']
    assert manifest['total_commits'] == 0 and manifest['total_chunks'] == 1
    assert json.loads(package['files']['ai_analysis_input/batch_001/001.json'])['commits'] == []


@pytest.mark.parametrize('options', [{'chunk_size': 0}, {'batch_size': 0}, {'chunk_size': True}])
def test_invalid_sizes_are_rejected(snapshots, options):
    with pytest.raises(ValueError, match='positive integer'):
        build(snapshots, **options)


def test_construction_does_not_write_files(snapshots, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    build(snapshots)
    assert list(tmp_path.iterdir()) == []


def test_deterministic_scores_do_not_change_ai_identity(snapshots):
    raw = sources(1)
    before = build_package(raw, {}, snapshots, VERSION)['manifest']['run_id']
    raw[0]['score'] = 0
    assert build_package(raw, {}, snapshots, VERSION)['manifest']['run_id'] == before
