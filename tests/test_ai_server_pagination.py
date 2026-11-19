"""V1 source pagination never limits discovery or expands rejected selections."""
import json
import pytest
from test_ai_batch_layout import prepare
from test_ai_server_runtime import basic, request, running

@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_v1_pagination_preserves_selection_and_catalogs(tmp_path, auth):
    cfg, cache, out, summary, manifest = prepare(tmp_path)
    with running(out / 'serve_ai.pyz', auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None

        def get(path):
            status, _, raw = request(port, path, authorization=token)
            assert status == 200
            return json.loads(raw)
        full = get('/v1/chunks')
        for query, offset, limit in [('', 0, None), ('?limit=2', 0, 2), ('?offset=2', 2, None), ('?limit=2&offset=1', 1, 2), ('?limit=0', 0, None), ('?limit=999', 0, 999), ('?offset=999', 999, None), ('?limit=%2B2&offset=%20%2B1%20', 1, 2)]:
            assert get('/v1/chunks' + query) == dict(full, chunks=full['chunks'][offset:offset + limit if limit else None])
        for query in ('?limit=abc', '?limit=1.5', '?limit=1_0', '?limit=-1', '?limit=&offset=', '?offset=-1&limit=2', '?offset=abc&limit=2', '?limit=1&limit=3', '?offset=1&offset=3', '?limti=1', '?limit=1&unknown=2'):
            assert request(port, '/v1/chunks' + query, authorization=token)[0] == 400
            assert get('/v1/chunks') == full
        for prefix in ('/v1', '/v2'):
            assert get(prefix + '/api?limit=1&offset=999') == get(prefix + '/api')
            for entry in get(prefix + '/api')['routes']:
                assert ('query_parameters' in entry) == (entry['path'] in ('/v1/chunks', '/v2/plan'))
                if entry['path'] == '/v2/plan':
                    assert set(entry['query_parameters']) == {
                        'max_commits_per_group', 'max_bytes_per_group', 'max_groups'}
