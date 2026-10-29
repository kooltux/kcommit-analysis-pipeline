"""The executable route registry is the API catalog's single source of truth."""
import json
from types import SimpleNamespace
import pytest
from test_ai_server_runtime import app, namespace, basic, request, running
from test_ai_server_front_page_content import PAGE


def invoke(values, path):
    handler = values['Handler'].__new__(values['Handler'])
    handler.path = path
    handler.server = SimpleNamespace(auth_credentials=None)
    responses = []
    handler.send_bytes = lambda data, kind=None: responses.append(json.loads(data))
    handler.send_error = lambda status, message=None: responses.append(status)
    handler.do_GET()
    assert len(responses) == 1
    return responses[0]


def test_api_is_derived_from_dispatch_registry(namespace, monkeypatch):
    def no_document(*args, **kwargs):
        raise AssertionError('API discovery must not read a packaged document')
    monkeypatch.setattr(namespace['ARCHIVE'], 'read', no_document)
    catalog = invoke(namespace, '/api')
    expected = {(r['method'], r['path']) for r in namespace['ROUTES']}
    assert {(r['method'], r['path']) for r in catalog['routes']} == expected
    assert len(catalog['routes']) == len(expected)
    assert all(r['description'] and r['response_content_type'] for r in catalog['routes'])
    upload = next(r for r in catalog['routes'] if r['method'] == 'POST')
    assert upload['request_schema'] == '/schema/result'
    assert upload['max_body_bytes'] == namespace['MAX_RESULT_BYTES']
    assert upload['parameters'] == ['name']


def test_registering_route_updates_dispatch_and_discovery(namespace):
    @namespace['route']('GET', '/test-route/<name>')
    def probe(self, name):
        """A route added only to executable code."""
        self.send_bytes(json.dumps({'name': name}).encode())
    assert invoke(namespace, '/test-route/batch_001/001.json') == {'name': 'batch_001/001.json'}
    entry = next(r for r in invoke(namespace, '/api')['routes'] if r['path'] == '/test-route/<name>')
    assert entry['description'] == probe.__doc__
    probe.__doc__ = 'Updated handler documentation.'
    assert next(r for r in invoke(namespace, '/api')['routes'] if r['path'] == entry['path'])['description'] == probe.__doc__
    @namespace['route']('DELETE', '/unsupported-test-route')
    def unsupported(self):
        """Not available without an HTTP method handler."""
    assert not any(r['method'] == 'DELETE' for r in invoke(namespace, '/api')['routes'])


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_standalone_zipapp_api_and_authentication(app, auth):
    with running(app, auth=auth) as (port, log, errors):
        if auth:
            assert request(port, '/api')[0] == 401
        token = basic(auth) if auth else None
        code, headers, raw = request(port, '/api?format=json', authorization=token)
        assert code == 200 and headers['Content-Type'] == 'application/json'
        assert int(headers['Content-Length']) == len(raw)
        catalog = json.loads(raw)
        assert catalog['authentication'] == {'required': bool(auth), 'scheme': 'Basic' if auth else None}
        assert {r['method'] for r in catalog['routes']} == {'GET', 'POST'}
        assert ('GET', '/api') in {(r['method'], r['path']) for r in catalog['routes']}
        assert 'reviewer:secret' not in raw.decode() and basic('reviewer:secret') not in raw.decode()
        assert request(port, '/api', method='POST', authorization=token)[0] == 405
        for method in ('HEAD', 'OPTIONS', 'DELETE'):
            assert request(port, '/api', method=method, authorization=token)[0] == 501
        for path, kind in (('/', 'text/markdown; charset=utf-8'), ('/prompt/analyst', 'text/markdown; charset=utf-8'), ('/chunks', 'application/json')):
            code, headers, raw = request(port, path, authorization=token)
            assert code == 200 and headers['Content-Type'] == kind
        assert request(port, '/api/extra', authorization=token)[0] == 404


def test_front_page_points_to_live_catalog_instead_of_a_second_route_table():
    text = PAGE.read_text(encoding='utf-8')
    assert 'GET /api' in text and 'route registry' in text
    assert '| Method | Path | Purpose |' not in text



def test_api_logical_order_is_independent_of_registration(namespace):
    expected = [('GET', path) for path in ['/api', '/api/version', '/',
                '/prompt/<name>', '/schema/<name>', '/batches', '/batch/<batch_id>',
                '/chunks', '/chunk/<name>', '/result/<name>']]
    expected += [('POST', '/result/<name>'), ('GET', '/export')]
    before = list(namespace['ROUTES'])
    first = invoke(namespace, '/api')
    assert [(entry['method'], entry['path']) for entry in first['routes']] == expected
    assert namespace['ROUTES'] == before
    namespace['ROUTES'].reverse()
    assert invoke(namespace, '/api') == first


def test_api_examples_use_current_source_ids_and_query_contract(namespace):
    namespace['NAMES'] = {'batch_003/008.json': 'hash'}
    namespace['BATCHES'] = {'batch_003': {'chunks': ['batch_003/008.json']}}
    entries = {entry['path']: entry for entry in invoke(namespace, '/api')['routes']}
    source = entries['/chunk/<name>']
    assert source['path_parameters']['name']['example'] == 'batch_003/008.json'
    assert source['examples'][0]['url'] == '/chunk/batch_003/008.json'
    batch = entries['/batch/<batch_id>']
    assert batch['path_parameters']['batch_id']['example'] == 'batch_003'
    assert batch['examples'][1]['url'] == '/batch/batch_003?limit=1&offset=0'
    assert batch['examples'][0] == {'method': 'GET', 'url': '/batch/batch_003'}
    upload = next(entry for entry in invoke(namespace, '/api')['routes'] if entry['method'] == 'POST')
    assert upload['examples'] == [{'method': 'POST', 'url': '/result/batch_003/008.json'}]
    assert upload['request_body']['required'] is True
    assert upload['request_body']['content_type'] == 'application/json'
    assert upload['request_body']['schema'] == {'$ref': '/schema/result'}
    for entry in entries.values():
        for example in entry['examples']:
            assert set(example) == {'method', 'url'}


def test_api_does_not_fabricate_ids_for_empty_source_lists(namespace):
    namespace['NAMES'] = {}
    namespace['BATCHES'] = {}
    entries = {entry['path']: entry for entry in invoke(namespace, '/api')['routes']}
    for path in ['/chunk/<name>', '/batch/<batch_id>', '/result/<name>']:
        assert entries[path]['examples'] == []
    assert invoke(namespace, '/schema/output') == 404


def test_api_prefers_route_specific_description(namespace):
    @namespace['route']('GET', '/description-test', description='Route-specific contract.')
    def probe(self):
        """Generic shared handler description."""
    entry = next(item for item in invoke(namespace, '/api')['routes'] if item['path'] == '/description-test')
    assert entry['description'] == 'Route-specific contract.'
    assert 'request_body' not in entry
