"""AI batching: real directories, identities and HTTP export/import."""
import io
import json
import zipfile
import pytest
from lib.ai_contract import NAME, digest, validate_chunk
from lib.commands.cmd_ai_import import import_results
from lib.stages.st08_prepare_ai import run
from test_st08_prepare_ai import setup_source
from test_ai_server_runtime import basic, request, running


def prepare(tmp_path, count=9, batch_size=2):
    cfg, cache, out = setup_source(tmp_path, [
        {'commit': f'{i:040x}', 'subject': 'Fix'} for i in range(count)])
    cfg['ai']['batch_size'] = batch_size
    cfg['paths']['cache_dir'] = str(cache)
    summary = run(cfg, str(cache), str(out))
    return cfg, cache, out, summary, json.loads((out / 'ai_analysis_bundle_manifest.json').read_text())


@pytest.mark.parametrize('count', [0, 1, 4, 5, 8, 9])
def test_batch_directories_and_manifest(tmp_path, count):
    cfg, cache, out, summary, manifest = prepare(tmp_path, count)
    chunks = max(1, (count + 1) // 2)
    batches = (chunks + 1) // 2
    assert summary['batch_count'] == manifest['total_batches'] == batches
    assert manifest['total_chunks'] == chunks
    assert manifest['batch_size'] == manifest['chunk_size'] == 2
    root = out / 'ai_analysis_input'
    assert sorted(p.name for p in root.iterdir()) == [f'batch_{n:03d}' for n in range(1, batches + 1)]
    names = [n for b in manifest['batches'] for n in b['chunks']]
    assert names == list(manifest['chunks']) and len(names) == chunks
    assert all(1 <= len(b['chunks']) <= 2 for b in manifest['batches'])
    assert sum(b['total_commits'] for b in manifest['batches']) == count
    with zipfile.ZipFile(out / 'serve_ai.pyz') as app:
        for i, name in enumerate(names):
            assert name == f'batch_{i // 2 + 1:03d}/{i + 1:03d}.json'
            data = (root / name).read_bytes()
            assert app.read('ai_analysis_input/' + name) == data
            assert digest(data) == manifest['chunks'][name]
            chunk = json.loads(data)
            assert chunk['chunk_info']['chunk_in_batch'] == i % 2 + 1
            assert validate_chunk(chunk, manifest['input_schema_checksum'], manifest['output_schema_checksum'], manifest['run_id'], name)
    assert run(cfg, str(cache), str(out))['run_id'] == summary['run_id']
    cfg['ai']['batch_size'] = 10
    assert run(cfg, str(cache), str(out))['run_id'] != summary['run_id']
    assert [p.name for p in root.iterdir()] == ['batch_001']


@pytest.mark.parametrize('name', ['../001.json', 'batch_001/../001.json', '/batch_001/001.json', 'batch_001//001.json', 'batch_001/%2e%2e/001.json'])
def test_unsafe_chunk_paths(name):
    assert NAME.fullmatch(name) is None


def test_http_export_import(tmp_path, monkeypatch):
    cfg, cache, out, summary, manifest = prepare(tmp_path)
    token = basic('reviewer:secret')
    with running(out / 'serve_ai.pyz', auth='reviewer:secret') as (port, log, errors):
        def req(path, **kwargs):
            return request(port, path, authorization=token, **kwargs)
        assert request(port, '/batches')[0] == 401
        batches = json.loads(req('/batches')[2])
        assert batches['total_batches'] == 3
        paths = [p['chunk'] for b in batches['batches'] for p in json.loads(req(b['url'])[2])['chunks']]
        assert paths == json.loads(req('/chunks')[2])['chunks']
        name = manifest['batches'][1]['chunks'][0]
        source = req('/chunk/' + name)[2]
        chunk = json.loads(source)
        result = {'schema_version': '1.0', 'run_id': manifest['run_id'], 'source_chunk': name,
                  'input_checksum': digest(source), 'input_schema_checksum': manifest['input_schema_checksum'],
                  'output_schema_checksum': manifest['output_schema_checksum'], 'analysis_status': 'partial',
                  'total_commits': len(chunk['commits']), 'analyzed_commits': 0, 'results': {}}
        bad = dict(result, source_chunk=name.split('/')[1])
        assert req('/result/' + name, method='PUT', body=json.dumps(bad).encode())[0] == 400
        payload = json.dumps(result).encode()
        assert req('/result/' + name, method='PUT', body=payload)[0] == 200
        assert req('/result/' + name)[2] == payload
        for path in ['/batch/batch_999', '/chunk/batch_999/001.json', '/chunk/batch_001/../001.json']:
            assert req(path)[0] == 404
        code, _, exported = req('/export')
        assert code == 200
    with zipfile.ZipFile(io.BytesIO(exported)) as app:
        assert app.read('results/' + name) == payload
        for n in manifest['chunks']:
            assert app.read('ai_analysis_input/' + n) == (out / 'ai_analysis_input' / n).read_bytes()
    bundle = tmp_path / 'returned.zip'
    bundle.write_bytes(exported)
    monkeypatch.setattr('lib.stages.st07_ai_report.run', lambda *args: None)
    assert import_results(cfg, str(bundle)) == {'run_id': manifest['run_id'], 'analyzed_commits': 0}
