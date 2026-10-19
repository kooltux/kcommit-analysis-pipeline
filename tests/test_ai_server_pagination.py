"""Pagination applies only to batch/chunk discovery, never the API catalog."""
import json
import pytest
from test_ai_server_runtime import app, namespace, basic, request, running
from test_ai_server_api import invoke
from test_ai_batch_layout import prepare

CASES = [('', 0, None), ('?limit=2', 0, 2), ('?offset=2', 2, None),
         ('?limit=2&offset=1', 1, 2), ('?limit=abc', 0, None),
         ('?limit=1.5', 0, None), ('?limit=1_0', 0, None), ('?limit=0', 0, None),
         ('?limit=-1', 0, None), ('?limit=&offset=', 0, None),
         ('?offset=-1&limit=2', 0, 2), ('?offset=abc&limit=2', 0, 2),
         ('?limit=999', 0, 999), ('?offset=999', 999, None),
         ('?limit=1&limit=3&offset=1', 1, 1), ('?limit=&limit=1', 0, None),
         ('?offset=1&offset=3', 1, None), ('?offset=0', 0, None),
         ('?limit=%2B2&offset=%20%2B1%20', 1, 2)]
ENDPOINTS = [('/batches', ('batches',)), ('/chunks', ('chunks',)),
             ('/batch/batch_002', ('chunks', 'results'))]


@pytest.fixture
def listings(namespace, monkeypatch):
    names = [f'batch_{b:03d}/{i:03d}.json' for b in range(1, 4) for i in range(b * 3 - 2, b * 3 + 1)]
    batches = {f'batch_{b:03d}': {'batch_id': f'batch_{b:03d}', 'batch_number': b,
               'chunks': names[(b - 1) * 3:b * 3], 'total_commits': 30} for b in range(1, 4)}
    monkeypatch.setitem(namespace, 'NAMES', dict.fromkeys(names, 'checksum'))
    monkeypatch.setitem(namespace, 'BATCHES', batches)
    return namespace


def check_page(full, page, fields, offset, limit):
    stop = offset + limit if limit is not None else None
    for key in fields:
        assert page[key] == full[key][offset:stop]
    assert {k: v for k, v in page.items() if k not in fields} == {k: v for k, v in full.items() if k not in fields}
    if 'results' in fields:
        assert [p.removeprefix('/chunk/') for p in page['chunks']] == [p.removeprefix('/result/') for p in page['results']]


@pytest.mark.parametrize('endpoint,fields', ENDPOINTS)
@pytest.mark.parametrize('query,offset,limit', CASES)
def test_discovery_pagination(listings, endpoint, fields, query, offset, limit):
    full = invoke(listings, endpoint)
    check_page(full, invoke(listings, endpoint + query), fields, offset, limit)
    assert invoke(listings, endpoint) == full


def test_api_describes_pagination_but_never_limits_itself(listings):
    full = invoke(listings, '/api')
    assert invoke(listings, '/api?limit=1&offset=999') == full
    for item in full['routes']:
        if item['path'] in {endpoint for endpoint, fields in ENDPOINTS} | {'/batch/<batch_id>'}:
            assert item['query_parameters'] == listings['LIST_QUERY_PARAMETERS']
        else:
            assert 'query_parameters' not in item


def test_standalone_paginated_http_and_complete_api(tmp_path):
    cfg, cache, out, summary, manifest = prepare(tmp_path)
    with running(out / 'serve_ai.pyz', auth='reviewer:secret') as (port, log, errors):
        def get(path):
            code, headers, body = request(port, path, authorization=basic('reviewer:secret'))
            assert code == 200 and headers['Content-Type'] == 'application/json'
            return json.loads(body)
        for endpoint, fields in ENDPOINTS:
            assert request(port, endpoint + '?limit=1')[0] == 401
            full = get(endpoint)
            for query, offset, limit in CASES:
                check_page(full, get(endpoint + query), fields, offset, limit)
        assert get('/api?limit=1&offset=999') == get('/api')
        assert request(port, '/batch/missing?limit=1', authorization=basic('reviewer:secret'))[0] == 404
