"""Regression and generated-zipapp coverage for the standalone AI smoke tool."""
import copy
import hashlib
import io
import json
from pathlib import Path
import runpy
import shutil
import zipfile
from urllib.parse import parse_qs
import pytest
from test_ai_batch_layout import prepare


@pytest.fixture
def tool():
    values = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'run_tests_ai'))
    return values['check_discovery'].__globals__


def fake_discovery(size):
    names = [f'batch_{i // 2 + 1:03d}/{i + 1:03d}.json' for i in range(size)]
    batches = [{'batch_id': f'batch_{i // 2 + 1:03d}', 'batch_number': i // 2 + 1,
                'chunks': names[i:i + 2], 'total_commits': len(names[i:i + 2]),
                'url': f'/batch/batch_{i // 2 + 1:03d}'} for i in range(0, size, 2)]
    routes = [{'method': 'GET', 'path': '/api'},
              {'method': 'GET', 'path': '/api/version'}] + [
        {'method': 'GET', 'path': p, 'query_parameters': {'limit': {}, 'offset': {}}}
        for p in ('/chunks', '/batches', '/batch/<batch_id>')]
    replies = {'/api': {'run_id': 'r', 'routes': routes},
               '/api/version': {'tool_version': 'v0.0.1', 'version_source': 'MANIFEST.json',
                                'captured_at': 'zipapp_generation'},
               '/chunks': {'run_id': 'r', 'chunks': ['/chunk/' + n for n in names]},
               '/batches': {'run_id': 'r', 'total_batches': len(batches), 'batches': batches}}
    for batch in batches:
        replies[batch['url']] = dict(batch, run_id='r',
            chunks=[{'chunk': '/chunk/' + n, 'result': '/result/' + n}
                    for n in batch['chunks']])
    return replies


def fake_expect(replies, fault=None):
    def expect(base, target, **kwargs):
        path, _, query = target.partition('?')
        full = copy.deepcopy(replies[path])
        result = copy.deepcopy(full)
        params = parse_qs(query, keep_blank_values=True)
        def number(name):
            try:
                return max(0, int(params.get(name, ['0'])[0]))
            except ValueError:
                return 0
        limit, offset = number('limit'), number('offset')
        if path != '/api':
            for key in ('chunks', 'batches'):
                if key in result:
                    result[key] = result[key][offset:offset + limit if limit else None]
        if query and fault == 'ignore_pagination' and path != '/api':
            result = full
        if query and fault == 'metadata' and path != '/api':
            result['run_id'] = 'wrong'
        if query and fault == 'misalign' and path.startswith('/batch/'):
            result['chunks'] = [dict(item, result='/result/wrong.json') for item in result['chunks']]
        if query and fault == 'paginate_api' and path == '/api':
            result['routes'] = result['routes'][:1]
        return json.dumps(result).encode()
    return expect


@pytest.mark.parametrize('size', [0, 1, 5])
def test_discovery_handles_empty_single_and_multiple_listings(tool, monkeypatch, size):
    replies = fake_discovery(size)
    monkeypatch.setitem(tool, 'expect', fake_expect(replies))
    assert tool['check_discovery']('unused') == replies['/chunks']


@pytest.mark.parametrize('fault', ['ignore_pagination', 'metadata', 'misalign', 'paginate_api'])
def test_smoke_checks_detect_broken_pagination(tool, monkeypatch, fault):
    monkeypatch.setitem(tool, 'expect', fake_expect(fake_discovery(5), fault))
    with pytest.raises(AssertionError):
        tool['check_discovery']('unused')


@pytest.mark.parametrize('omit', [False, True])
def test_export_checks_require_all_sources_after_pagination(tool, omit):
    sources = {'batch_001/001.json': b'first', 'batch_002/002.json': b'second'}
    listing = {'run_id': 'r', 'chunks': ['/chunk/' + n for n in sources]}
    manifest = {'run_id': 'r', 'chunks': {n: hashlib.sha256(v).hexdigest() for n, v in sources.items()}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('ai_analysis_bundle_manifest.json', json.dumps(manifest))
        for index, (name, data) in enumerate(sources.items()):
            if not omit or index == 0:
                archive.writestr('ai_analysis_input/' + name, data)
    if omit:
        with pytest.raises(AssertionError, match='omitted or added'):
            tool['check_export'](buffer.getvalue(), listing)
    else:
        tool['check_export'](buffer.getvalue(), listing)


@pytest.mark.parametrize('count', [0, 1, 9])
def test_full_smoke_with_generated_zipapp(tool, tmp_path, count):
    if shutil.which('curl') is None:
        pytest.skip('curl is required by the standalone smoke tool')
    cfg, cache, out, summary, manifest = prepare(tmp_path, count=count)
    tool['smoke'](out / 'serve_ai.pyz')
