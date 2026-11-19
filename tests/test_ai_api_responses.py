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
from ai_http_helpers import workflow_paths


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
    if definition.get('$ref', '').startswith(('/v1/schema/', '/v2/schema')):
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


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_versioned_catalogs_publish_and_enforce_response_contracts(app, package, auth):
    from test_ai_versioned_runtime import contributions
    from jsonschema import ValidationError
    documents = contributions(package)
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        for prefix in ('/v1', '/v2'):
            status, _, raw = request(port, prefix + '/api', authorization=token)
            assert status == 200
            catalog = json.loads(raw)
            entries = {(item['method'], item['path']): item for item in catalog['routes']}
            for definition in catalog['response_schemas'].values():
                Draft202012Validator.check_schema(definition)
            for item in entries.values():
                assert item['responses']['200']['schema'], (item['method'], item['path'])
                assert ('401' in item['responses']) == bool(auth)
            def check(path, pattern, method='GET', value=None):
                response = request(port, path, method=method,
                    body=encode(value) if value is not None else None, authorization=token)
                assert response[0] == 200
                contract = entries[method, pattern]['responses']['200']
                check_response(catalog, contract, response, port, token)
                definition = resolve(catalog, contract['schema'])
                if definition.get('required'):
                    invalid = json.loads(response[2])
                    del invalid[definition['required'][0]]
                    with pytest.raises(ValidationError):
                        Draft202012Validator(definition).validate(invalid)
                return response
            check(prefix + '/api', prefix + '/api')
            check(prefix + '/schema/workflow', prefix + '/schema/<name>')
            for role in ('analyst', 'cve', 'reviewer'):
                check(prefix + '/validate/role/' + role, prefix + '/validate/role/<role>',
                      'POST', documents[role])
            validation, submission = workflow_paths(port, prefix, token=token)
            validation_pattern = '/v1/validate/workflow' if prefix == '/v1' else '/v2/validate/<group_id>'
            submission_pattern = '/v1/result' if prefix == '/v1' else '/v2/result/<group_id>'
            check(validation, validation_pattern, 'POST', documents)
            check(submission, submission_pattern, 'POST', documents)
            check(prefix + '/export', prefix + '/export')
            if prefix == '/v1':
                check(prefix + '/chunks', prefix + '/chunks')
            else:
                response = check(prefix + '/plan', prefix + '/plan')
                for group in json.loads(response[2])['groups']:
                    check(prefix + '/group/' + group['group_id'], prefix + '/group/<group_id>')
            response = request(port, prefix + '/schema/unknown', authorization=token)
            assert response[0] == 404
            check_response(catalog, catalog['error_responses']['404'], response, port, token)
            if auth:
                response = request(port, prefix + '/api')
                assert response[0] == 401
                check_response(catalog, catalog['error_responses']['401'], response, port)
