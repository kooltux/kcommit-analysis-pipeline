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
