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
    handler.send_error = lambda status: responses.append(status)
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
    upload = next(r for r in catalog['routes'] if r['method'] == 'PUT')
    assert upload['request_schema'] == '/schema/output'
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
        assert {r['method'] for r in catalog['routes']} == {'GET', 'PUT', 'POST'}
        assert ('GET', '/api') in {(r['method'], r['path']) for r in catalog['routes']}
        assert 'secret' not in raw.decode() and 'reviewer' not in raw.decode()
        assert request(port, '/api', method='POST', authorization=token)[0] == 404
        for method in ('HEAD', 'OPTIONS', 'DELETE'):
            assert request(port, '/api', method=method, authorization=token)[0] == 501
        for path, kind in (('/', 'text/markdown; charset=utf-8'), ('/prompt', 'text/markdown'), ('/chunks', 'application/json')):
            code, headers, raw = request(port, path, authorization=token)
            assert code == 200 and headers['Content-Type'] == kind
        assert request(port, '/api/extra', authorization=token)[0] == 404


def test_front_page_points_to_live_catalog_instead_of_a_second_route_table():
    text = PAGE.read_text(encoding='utf-8')
    assert 'GET /api' in text and 'route registry' in text
    assert '| Method | Path | Purpose |' not in text
