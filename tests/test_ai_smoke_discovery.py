"""Regression and generated-zipapp coverage for the standalone AI smoke tool."""
import copy
import hashlib
import io
import json
import re
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
    groups = ['discovery', 'contract', 'sources', 'validation', 'results', 'other']
    routes = [{'method': 'GET', 'path': '/api', 'group': 'discovery'},
              {'method': 'GET', 'path': '/api/version', 'group': 'discovery'},
              {'method': 'GET', 'path': '/schema/<name>', 'group': 'contract'}] + [
        {'method': 'GET', 'path': p, 'group': 'sources',
         'query_parameters': {'limit': {'default': 0, 'example': 1},
                              'offset': {'default': 0, 'example': 0}}}
        for p in ('/batches', '/batch/<batch_id>', '/chunks')]
    for route in routes:
        route.update(path_parameters={}, examples=[])
        url = route['path']
        if url == '/schema/<name>':
            route['path_parameters']['name'] = {'type': 'string', 'enum': ['result'], 'example': 'result'}
            url = '/schema/result'
        if '<batch_id>' in url:
            batch_id = batches[0]['batch_id'] if batches else None
            route['path_parameters']['batch_id'] = {'type': 'string', 'example': batch_id}
            if batch_id is not None:
                url = url.replace('<batch_id>', batch_id)
        if '<' not in url:
            route['examples'].append({'method': 'GET', 'url': url})
            if 'query_parameters' in route:
                route['examples'].append({'method': 'GET', 'url': url + '?limit=1&offset=0'})
    replies = {'/api': {'run_id': 'r', 'groups': groups, 'routes': routes},
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
        paginated = path in ('/chunks', '/batches') or path.startswith('/batch/')
        invalid = paginated and (bool(set(params) - {'limit', 'offset'}) or any(
            len(values) != 1 or not re.fullmatch(r'[+-]?[0-9]+', values[0].strip())
            or int(values[0]) < 0 for values in params.values()))
        status = 400 if invalid and fault != 'accept_invalid' else 200
        assert kwargs.get('status', 200) == status, 'Pagination HTTP status mismatch'
        if invalid:
            return b'{"error":"invalid_pagination"}'
        limit = int(params.get('limit', ['0'])[0]) if paginated else 0
        offset = int(params.get('offset', ['0'])[0]) if paginated else 0
        if path != '/api':
            for key in ('chunks', 'batches'):
                if key in result:
                    result[key] = result[key][offset:offset + limit if limit else None]
        if query and fault == 'ignore_pagination' and path != '/api':
            result = full
        if query and fault == 'metadata' and (path in ('/chunks', '/batches') or path.startswith('/batch/')):
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


@pytest.mark.parametrize('fault,message', [
    ('ignore_pagination', 'Pagination or metadata mismatch: /chunks'),
    ('metadata', 'Pagination or metadata mismatch: /chunks'),
    ('misalign', 'Pagination or metadata mismatch: /batch/'),
    ('paginate_api', 'API catalog was paginated'),
    ('accept_invalid', 'Pagination HTTP status mismatch'),
])
def test_smoke_checks_detect_broken_pagination(tool, monkeypatch, fault, message):
    monkeypatch.setitem(tool, 'expect', fake_expect(fake_discovery(5), fault))
    with pytest.raises(AssertionError, match=message):
        tool['check_discovery']('unused')


@pytest.mark.parametrize('fault,message', [
    ('missing_schema', 'Missing canonical result schema'),
    ('removed_alias', 'Removed schema alias is advertised'),
    ('group_order', 'API groups are not logically ordered'),
    ('examples', 'Missing API parameter examples'),
    ('path_parameters', 'Missing API parameter examples'),
])
def test_smoke_checks_detect_invalid_api_contract(tool, monkeypatch, fault, message):
    replies = fake_discovery(1)
    routes = replies['/api']['routes']
    if fault == 'missing_schema':
        routes[:] = [route for route in routes if route['path'] != '/schema/<name>']
    elif fault == 'removed_alias':
        routes.append(dict(method='GET', path='/schema/output', group='contract',
                           path_parameters={}, examples=[]))
    elif fault == 'group_order':
        routes.reverse()
    else:
        del routes[0][fault]
    monkeypatch.setitem(tool, 'expect', fake_expect(replies))
    with pytest.raises(AssertionError, match=message):
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
