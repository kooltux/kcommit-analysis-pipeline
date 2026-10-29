"""Advertised response contracts match generated-server success and error bodies."""
import io
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from lib.ai_contract import encode
from test_ai_package_server import app, package, workflow
from test_ai_preparation import snapshots
from test_ai_server_runtime import namespace, basic, request, running


def resolve(catalog, value):
    while '$ref' in value and value['$ref'].startswith('#/'):
        target = catalog
        for name in value['$ref'][2:].split('/'):
            target = target[name]
        value = target
    return value


def check_response(catalog, contract, response, port, token=None):
    status, headers, body = response
    spec = resolve(catalog, contract)
    assert headers['Content-Type'] == spec['content_type']
    definition = resolve(catalog, spec['schema'])
    if definition.get('$ref', '').startswith('/schema/'):
        code, _, raw = request(port, definition['$ref'], authorization=token)
        assert code == 200
        definition = json.loads(raw)
    if definition.get('$ref') == 'https://json-schema.org/draft/2020-12/schema':
        Draft202012Validator.check_schema(json.loads(body))
    elif spec['content_type'] == 'application/json':
        Draft202012Validator(definition).validate(json.loads(body))
    elif spec.get('body_encoding') == 'binary':
        assert body.startswith(b'PK')
    else:
        assert isinstance(body.decode('utf-8'), str)
    for name in spec.get('headers', {}):
        assert name in headers
    if status != 200:
        assert json.loads(body)['error']['status'] == status
        assert json.loads(body)['error']['code'] == spec['example']['error']['code']


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_generated_api_response_contracts(app, workflow, auth):
    name, documents = workflow
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        raw_catalog = request(port, '/api', authorization=token)
        catalog = json.loads(raw_catalog[2])
        entries = {(entry['method'], entry['path']): entry for entry in catalog['routes']}
        for definition in catalog['response_schemas'].values():
            Draft202012Validator.check_schema(definition)
        for contract in catalog['error_responses'].values():
            Draft202012Validator(resolve(catalog, contract['schema'])).validate(contract['example'])
        for entry in entries.values():
            assert ('401' in entry['responses']) == bool(auth)
            assert entry['responses']['200']['schema']
            for contract in entry['responses'].values():
                spec = resolve(catalog, contract)
                if 'example' in spec:
                    Draft202012Validator(resolve(catalog, spec['schema'])).validate(spec['example'])
        paths = [('/api', '/api'), ('/api/version', '/api/version'), ('/', '/'),
                 ('/contract', '/contract'), ('/prompt/analyst', '/prompt/<name>'),
                 ('/schema/input', '/schema/<name>'), ('/batches', '/batches'),
                 ('/batch/' + name.split('/')[0], '/batch/<batch_id>'),
                 ('/chunks', '/chunks'), ('/chunk/' + name, '/chunk/<name>'),
                 ('/metadata/' + name, '/metadata/<name>')]
        for path, pattern in paths:
            entry = entries['GET', pattern]
            response = request(port, path, authorization=token)
            assert response[0] == 200
            check_response(catalog, entry['responses']['200'], response, port, token)
        for role in ('analyst', 'cve', 'reviewer'):
            entry = entries['POST', '/validate/role/<role>/<name>']
            response = request(port, '/validate/role/' + role + '/' + name,
                               method='POST', body=encode(documents[role]), authorization=token)
            assert response[0] == 200
            check_response(catalog, entry['responses']['200'], response, port, token)
        entry = entries['POST', '/validate/workflow/<name>']
        response = request(port, '/validate/workflow/' + name, method='POST',
                           body=encode(documents), authorization=token)
        assert response[0] == 200
        check_response(catalog, entry['responses']['200'], response, port, token)
        assert request(port, '/result/' + name, authorization=token)[0] == 404
        assert not app.with_name(app.name + '.results').exists()
        response = request(port, '/result/' + name, method='POST',
                           body=encode(documents['result']), authorization=token)
        assert response[0] == 200
        check_response(catalog, entries['POST', '/result/<name>']['responses']['200'], response, port, token)
        for path, pattern in [('/result/' + name, '/result/<name>'), ('/export', '/export')]:
            response = request(port, path, authorization=token)
            assert response[0] == 200
            check_response(catalog, entries['GET', pattern]['responses']['200'], response, port, token)
        failures = [('/chunks?limit=bad', 'GET', None, 400),
                    ('/validate/workflow/' + name, 'POST', b'{}', 400),
                    ('/validate/role/analyst/' + name, 'POST', b'{}', 400),
                    ('/prompt/unknown', 'GET', None, 404),
                    ('/api', 'POST', b'{}', 405), ('/api', 'DELETE', None, 501)]
        for path, method, body, status in failures:
            response = request(port, path, method=method, body=body, authorization=token)
            assert response[0] == status
            check_response(catalog, catalog['error_responses'][str(status)], response, port, token)
        if auth:
            response = request(port, '/api')
            assert response[0] == 401
            check_response(catalog, entries['GET', '/api']['responses']['401'], response, port)


def test_response_registry_is_extensible_and_not_mutated(namespace):
    @namespace['route']('GET', '/response-probe', response_schema='#/response_schemas/upload_ack',
                        response_example={'status': 'ok'}, response_description='Probe response.')
    def probe(self):
        pass
    original = json.dumps([{k: v for k, v in entry.items() if k not in ('handler', 'matcher')}
                           for entry in namespace['ROUTES']], sort_keys=True)
    for auth in (None, b'user:secret', None):
        handler = namespace['Handler'].__new__(namespace['Handler'])
        handler.server = SimpleNamespace(auth_credentials=auth)
        responses = []
        handler.send_bytes = lambda body: responses.append(json.loads(body))
        handler.api()
        entry = next(item for item in responses[0]['routes'] if item['path'] == '/response-probe')
        assert entry['responses']['200']['description'] == 'Probe response.'
        assert entry['responses']['200']['example'] == {'status': 'ok'}
        assert ('401' in entry['responses']) == bool(auth)
    assert json.dumps([{k: v for k, v in entry.items() if k not in ('handler', 'matcher')}
                       for entry in namespace['ROUTES']], sort_keys=True) == original


@pytest.mark.parametrize('status', [400, 401, 404, 405, 408, 414, 431, 500, 501])
def test_actual_error_envelopes_match_shared_contract(namespace, status):
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.command = 'GET'
    handler.allowed_methods = ['GET']
    handler.wfile = io.BytesIO()
    headers = {}
    codes = []
    handler.send_response = codes.append
    handler.send_header = lambda name, value: headers.update({name: value})
    handler.end_headers = lambda: None
    handler.send_error(status, 'diagnostic detail')
    assert codes == [status]
    catalog = {'response_schemas': namespace['RESPONSE_SCHEMAS']}
    contract = namespace['error_responses']()[str(status)]
    check_response(catalog, contract, (status, headers, handler.wfile.getvalue()), None)
    if status >= 500:
        assert 'diagnostic detail' not in handler.wfile.getvalue().decode()
