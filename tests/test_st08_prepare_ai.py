"""Stage 08 bundle preparation tests."""
import json
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
    cfg = {'paths': {'output_dir': str(outdir)}, 'ai': {'chunk_size': 2}}
    return cfg, cache, outdir


def test_chunks_and_zipapp_follow_manifest(tmp_path):
    commits = [{'commit': f'{i:040x}', 'subject': f'Fix {i}'} for i in range(3)]
    cfg, cache, outdir = setup_source(tmp_path, commits)
    summary = run(cfg, str(cache), str(outdir))
    assert summary['total_commits'] == 3
    assert summary['chunk_count'] == 2
    manifest = json.loads((outdir / 'ai_analysis_bundle_manifest.json').read_text())
    assert set(manifest['chunks']) == {'1.json', '2.json'}
    for name in manifest['chunks']:
        data = (outdir / 'ai_analysis_input' / name).read_bytes()
        assert digest(data) == manifest['chunks'][name]
        chunk = json.loads(data)
        assert validate_chunk(chunk, manifest['input_schema_checksum'],
                              manifest['output_schema_checksum'], manifest['run_id'], name)
        assert 'score' not in chunk['commits'][0]
    with zipfile.ZipFile(outdir / 'serve_ai.pyz') as app:
        assert app.read('ai_analysis_input/1.json') == (outdir / 'ai_analysis_input' / '1.json').read_bytes()
        assert app.read('ai_analysis_bundle_manifest.json') == (outdir / 'ai_analysis_bundle_manifest.json').read_bytes()


def test_empty_source_has_one_empty_chunk(tmp_path):
    cfg, cache, outdir = setup_source(tmp_path, [])
    summary = run(cfg, str(cache), str(outdir))
    assert summary['total_commits'] == 0
    assert summary['chunk_count'] == 1
    chunk = json.loads((outdir / 'ai_analysis_input' / '1.json').read_text())
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
    assert CONFIG_SCHEMA['ai']['front_page_path'] == {'type': 'path'}
