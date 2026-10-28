"""Stage 08 bundle preparation tests."""
import json
import os
import zipfile

import pytest

from lib.ai_contract import digest, validate_chunk
from lib.stages.st08_prepare_ai import run


def setup_source(tmp_path, commits):
    cache = tmp_path / 'cache'
    outdir = tmp_path / 'output'
    cache.mkdir()
    (cache / 'prefilter_kept_commits.json').write_text(json.dumps(commits), encoding='utf-8')
    (cache / 'product_map.json').write_text('{}', encoding='utf-8')
    samples = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'configs', 'ai')
    cfg = {'paths': {'output_dir': str(outdir)}, 'ai': {
        'chunk_size': 2, 'prompts_dir': os.path.join(samples, 'prompts'),
        'front_page_path': os.path.join(samples, 'ai_server_front_page.md'),
        'schemas_dir': os.path.join(samples, 'schemas')}}
    return cfg, cache, outdir


def test_chunks_and_zipapp_follow_manifest(tmp_path):
    commits = [{'commit': f'{i:040x}', 'subject': f'Fix {i}'} for i in range(3)]
    cfg, cache, outdir = setup_source(tmp_path, commits)
    summary = run(cfg, str(cache), str(outdir))
    assert summary['total_commits'] == 3
    assert summary['chunk_count'] == 2
    manifest = json.loads((outdir / 'ai_analysis_bundle_manifest.json').read_text())
    assert set(manifest['chunks']) == {'batch_001/001.json', 'batch_001/002.json'}
    for name in manifest['chunks']:
        data = (outdir / 'ai_analysis_input' / name).read_bytes()
        assert digest(data) == manifest['chunks'][name]
        chunk = json.loads(data)
        assert validate_chunk(chunk, manifest['input_schema_checksum'],
                              manifest['output_schema_checksum'], manifest['run_id'], name)
        assert 'score' not in chunk['commits'][0]
    with zipfile.ZipFile(outdir / 'serve_ai.pyz') as app:
        assert app.read('ai_analysis_input/batch_001/001.json') == (outdir / 'ai_analysis_input' / 'batch_001/001.json').read_bytes()
        assert app.read('ai_analysis_bundle_manifest.json') == (outdir / 'ai_analysis_bundle_manifest.json').read_bytes()


def test_empty_source_has_one_empty_chunk(tmp_path):
    cfg, cache, outdir = setup_source(tmp_path, [])
    summary = run(cfg, str(cache), str(outdir))
    assert summary['total_commits'] == 0
    assert summary['chunk_count'] == 1
    chunk = json.loads((outdir / 'ai_analysis_input' / 'batch_001/001.json').read_text())
    assert chunk['commits'] == []
    assert chunk['chunk_info']['start_index'] == chunk['chunk_info']['end_index'] == 0

@pytest.mark.parametrize('size', [0, -1, True, '2'])
def test_invalid_chunk_size_rejected(tmp_path, size):
    cfg, cache, outdir = setup_source(tmp_path, [])
    cfg['ai']['chunk_size'] = size
    with pytest.raises(ValueError, match='chunk_size'):
        run(cfg, str(cache), str(outdir))


@pytest.mark.parametrize('custom', [False, True])
def test_front_page_packaged(tmp_path, custom):
    cfg, cache, outdir = setup_source(tmp_path, [])
    content = '# Custom server guide\n\nPurpose: assessment exchange.\n'
    if custom:
        path = tmp_path / 'custom.md'
        path.write_text(content, encoding='utf-8')
        cfg['ai']['front_page_path'] = str(path)
    run(cfg, str(cache), str(outdir))
    data = (outdir / 'ai_server_front_page.md').read_bytes()
    assert data.strip()
    if custom:
        assert data.decode('utf-8') == content
    with zipfile.ZipFile(outdir / 'serve_ai.pyz') as app:
        assert app.read('ai_server_front_page.md') == data


@pytest.mark.parametrize('content', [None, b'', b' \n', b'\xff'])
def test_invalid_front_page_fails_before_outputs(tmp_path, content):
    cfg, cache, outdir = setup_source(tmp_path, [])
    path = tmp_path / 'front.md'
    if content is not None:
        path.write_bytes(content)
    cfg['ai']['front_page_path'] = str(path)
    with pytest.raises(ValueError, match='ai.front_page_path'):
        run(cfg, str(cache), str(outdir))
    assert not outdir.exists()


def test_front_page_config_registered():
    from lib.config import CONFIG_SCHEMA
    spec = CONFIG_SCHEMA['ai']['front_page_path']
    assert spec['type'] == 'path' and spec['kind'] == 'file' and spec['needs'] == 'ai'
    assert spec['default'] == 'ai/ai_server_front_page.md'


def test_selected_assets_published_and_embedded(tmp_path):
    from pathlib import Path
    cfg, cache, out = setup_source(tmp_path, [{'commit': 'a' * 40}])
    run(cfg, str(cache))
    manifest = json.loads((out / 'ai_analysis_bundle_manifest.json').read_bytes())
    assert len(manifest['contract_assets']) >= 9
    with zipfile.ZipFile(out / 'serve_ai.pyz') as app:
        for name, expected in manifest['contract_assets'].items():
            group, filename = name.split('/')
            data = (Path(cfg['ai'][group + '_dir']) / filename).read_bytes()
            assert digest(data) == expected
            assert (out / 'ai_contract' / name).read_bytes() == data
            assert app.read('ai_contract/' + name) == data
    for alias, selected in [('input', 'input'), ('result', 'result')]:
        assert (out / ('ai_analysis_' + alias + '_schema.json')).read_bytes() == (out / 'ai_contract/schemas' / (selected + '.json')).read_bytes()


def test_generation_failure_preserves_existing_package(tmp_path, monkeypatch):
    from lib.stages import st08_prepare_ai
    cfg, cache, out = setup_source(tmp_path, [{'commit': 'a' * 40}])
    run(cfg, str(cache))
    before = {p.relative_to(out): p.read_bytes() for p in out.rglob('*') if p.is_file()}
    def fail(*args):
        raise ValueError('generation failed')
    monkeypatch.setattr(st08_prepare_ai, 'generate_ai_package_server', fail)
    with pytest.raises(ValueError, match='generation failed'):
        run(cfg, str(cache))
    assert {p.relative_to(out): p.read_bytes() for p in out.rglob('*') if p.is_file()} == before
    assert not list(tmp_path.glob('.ai-prepare-*'))


def test_asset_identity_and_stale_tree_replacement(tmp_path):
    import shutil
    cfg, cache, out = setup_source(tmp_path, [{'commit': 'a' * 40}])
    selected = tmp_path / 'prompts'
    shutil.copytree(cfg['ai']['prompts_dir'], selected)
    cfg['ai']['prompts_dir'] = str(selected)
    first = run(cfg, str(cache))
    (selected / 'extra.md').write_bytes(b'# Additional instruction\n')
    assert run(cfg, str(cache))['run_id'] != first['run_id']
    assert (out / 'ai_contract/prompts/extra.md').is_file()
    (selected / 'extra.md').unlink()
    assert run(cfg, str(cache))['run_id'] == first['run_id']
    assert not (out / 'ai_contract/prompts/extra.md').exists()


@pytest.mark.parametrize('asset', ['prompts/analyst.md', 'schemas/reviewer.json'])
def test_import_rejects_modified_contract_tree(tmp_path, asset):
    from lib.ai_exchange import Progress, WorkPackage
    cfg, cache, out = setup_source(tmp_path, [])
    run(cfg, str(cache))
    target = out / 'ai_contract' / asset
    target.write_bytes(target.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='contract checksum mismatch'):
        WorkPackage(cfg, Progress('test'))
