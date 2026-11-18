"""Portable storage parity, transactional publication and live receipt regressions."""
import copy
import importlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from ai_runtime_helpers import runtime_namespace
from ai_submission_helpers import role_body
from lib import ai_result_store as storage
from lib.ai_contract import digest, encode, result_properties, validate_result
from lib.ai_preparation import build_package
from lib.ai_source import SourceIndex
from lib.manifest import VERSION
from test_ai_package_server import app, snapshots
from test_ai_server_runtime import request as http_request, running


@pytest.fixture
def package(snapshots):
    return build_package([{'commit': 'a' * 40}, {'commit': 'b' * 40}], {}, snapshots,
                         VERSION, chunk_size=2, batch_size=2)


def document(package, results):
    manifest = package['manifest']
    name = next(iter(manifest['chunks']))
    return dict(schema_version='1.0', run_id=manifest['run_id'], source_chunk=name,
                input_checksum=manifest['chunks'][name],
                input_schema_checksum=manifest['input_schema_checksum'],
                output_schema_checksum=manifest['output_schema_checksum'],
                total_commits=2, analyzed_commits=len(results),
                analysis_status='complete' if len(results) == 2 else 'partial', results=results)


@pytest.fixture
def record(package):
    schema = json.loads(package['files']['ai_analysis_result_schema.json'])
    value = {}
    for key, spec in result_properties(schema).items():
        kind = spec['type']
        value[key] = (None if isinstance(kind, list) else False if kind == 'boolean'
                      else [] if kind == 'array' else spec.get('enum', ['evidence'])[0])
    value.update(rv_agreement='agree', ai_risks_if_not_backported=['none'])
    return value


@pytest.fixture(params=['host', 'portable'])
def backend(request, package, app):
    if request.param == 'host':
        source = SourceIndex(package['manifest'],
            lambda name: package['files']['ai_analysis_input/' + name])
        schema = json.loads(package['files']['ai_analysis_result_schema.json'])
        def validate(name, value):
            return validate_result(value, source.context(name), schema, source.checksums[name])
        yield storage, storage.ResultStore(str(app) + '.results', source, validate)
    else:
        with runtime_namespace(app) as values:
            module = importlib.import_module(values['__package__'] + '.result_store')
            yield module, module.ResultStore(values['RESULTS'], values['SOURCE_INDEX'], values['validate'])


def test_packaged_store_is_exact_host_source(app):
    with zipfile.ZipFile(app) as archive:
        assert archive.read('kcap_ai_runtime/result_store.py') == Path(storage.__file__).read_bytes()


@pytest.mark.parametrize('failure', ['invalid', 'blob', 'index'])
def test_legacy_migration_and_failed_publication(backend, package, record, monkeypatch, failure):
    module, store = backend
    first = document(package, {'a' * 40: record})
    name = first['source_chunk']
    legacy = Path(store.root) / name
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(encode(first))
    assert store.read_chunk(name) == encode(first)
    assert not Path(store.directory).exists()
    before = store.write_chunk(name, document(package, {'b' * 40: record}))
    assert json.loads(before)['analysis_status'] == 'complete'
    legacy.write_bytes(b'invalid legacy data must not override the published index')
    assert store.read_chunk(name) == before
    candidate = document(package, {'a' * 40: copy.deepcopy(record)})
    if failure == 'invalid':
        candidate['results']['a' * 40] = {}
    else:
        atomic = module._atomic_bytes
        def fail(path, data):
            if (failure == 'index') == (Path(path).parent.name == 'chunks'):
                raise OSError('injected storage failure')
            return atomic(path, data)
        monkeypatch.setattr(module, '_atomic_bytes', fail)
    with pytest.raises((ValueError, OSError)):
        store.write_chunk(name, candidate)
    assert store.read_chunk(name) == before
    assert not list(Path(store.root).rglob('.result-*'))


