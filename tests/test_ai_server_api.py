"""Two complete catalogs are derived from their own executable route registries."""
import copy
import json
from types import SimpleNamespace
import pytest
from test_ai_package_server import app, package, snapshots
from test_ai_server_runtime import namespace, basic, request, running

def invoke(values, path):
    handler = values['Handler'].__new__(values['Handler'])
    handler.path = path
    handler.server = SimpleNamespace(auth_credentials=None)
    result = []
    handler.send_bytes = lambda raw, kind=None: result.append(json.loads(raw))
    handler.send_error = lambda status, message=None: result.append(status)
    handler.do_GET()
    assert len(result) == 1
    return result[0]

@pytest.mark.parametrize('prefix', ['/v1', '/v2'])
def test_catalog_matches_only_its_executable_registry(namespace, prefix, monkeypatch):

    def forbidden(*args):
        raise AssertionError('Discovery must not read an archived catalog')
    monkeypatch.setattr(namespace['ARCHIVE'], 'read', forbidden)
    catalog = invoke(namespace, prefix + '/api')
    expected = {(r['method'], r['path']) for r in namespace['ROUTES'] if r['path'].startswith(prefix + '/')}
    assert {(r['method'], r['path']) for r in catalog['routes']} == expected
    assert len(catalog['routes']) == len(expected)
    assert all((r['description'] and r['response_content_type'] for r in catalog['routes']))
    assert {prefix + p for p in ('/api', '/version', '/contract', '/prompt/<name>', '/schema/<name>')} <= {r['path'] for r in catalog['routes']}
    namespace['ROUTES'].reverse()
    assert invoke(namespace, prefix + '/api?limit=1&offset=999') == catalog

@pytest.mark.parametrize('prefix', ['/v1', '/v2'])
def test_registering_route_updates_only_its_own_catalog(namespace, prefix):
    other = '/v2' if prefix == '/v1' else '/v1'
    before = invoke(namespace, other + '/api')

    @namespace['route']('GET', prefix + '/probe/<name>', description='Explicit probe contract.')
    def probe(self, name):
        self.send_bytes(json.dumps({'name': name}).encode())
    assert invoke(namespace, prefix + '/probe/value') == {'name': 'value'}
    item = next((r for r in invoke(namespace, prefix + '/api')['routes'] if r['path'] == prefix + '/probe/<name>'))
    assert item['description'] == 'Explicit probe contract.'
    assert invoke(namespace, other + '/api') == before

    @namespace['route']('DELETE', prefix + '/unsupported')
    def unsupported(self):
        pass
    assert not any((r['method'] == 'DELETE' for r in invoke(namespace, prefix + '/api')['routes']))
    with pytest.raises(ValueError, match='require /v1/'):
        namespace['route']('GET', '/unversioned')

@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_catalog_http_authentication_and_method_contract(app, auth):
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        for prefix in ('/v1', '/v2'):
            if auth:
                assert request(port, prefix + '/api')[0] == 401
            status, headers, raw = request(port, prefix + '/api', authorization=token)
            assert status == 200 and int(headers['Content-Length']) == len(raw)
            assert json.loads(raw)['authentication'] == dict(required=bool(auth), scheme='Basic' if auth else None)
            assert 'reviewer:secret' not in raw.decode()
            assert request(port, prefix + '/api', method='POST', body=b'{}', authorization=token)[0] == 405
            for method in ('HEAD', 'OPTIONS', 'DELETE'):
                assert request(port, prefix + '/api', method=method, authorization=token)[0] == 501
        for path in ('/api', '/api/version', '/v1', '/v2', '/xxxxx', '/contract', '/prompt/analyst', '/schema/input', '/chunks', '/result', '/export'):
            for method in ('GET', 'POST', 'PUT', 'HEAD'):
                assert request(port, path, method=method, body=b'{}' if method == 'POST' else None, authorization=token)[0] == 404
        assert request(port, '/', authorization=token)[0] == 200
