"""POST and PUT share upload validation, storage, authentication and discovery."""
import io
import json
from pathlib import Path
import zipfile

import pytest
from test_ai_server_runtime import app, namespace, basic, request, running


def test_upload_routes_share_handler_and_contract(namespace):
    routes = [r for r in namespace['ROUTES'] if r['path'] == '/result/<name>'
              and r['method'] in ('POST', 'PUT')]
    assert {r['method'] for r in routes} == {'POST', 'PUT'}
    assert routes[0]['handler'] is routes[1]['handler']
    assert {k: v for k, v in routes[0].items() if k != 'method'} == {
        k: v for k, v in routes[1].items() if k != 'method'}


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
@pytest.mark.parametrize('methods', [('PUT', 'POST'), ('POST', 'PUT')])
def test_both_upload_methods_replace_validate_and_export(app, auth, methods):
    with zipfile.ZipFile(app) as archive:
        manifest = json.loads(archive.read('ai_analysis_bundle_manifest.json'))
    result = dict(schema_version='1.0', run_id=manifest['run_id'], source_chunk='1.json',
                  input_checksum=manifest['chunks']['1.json'], input_schema_checksum='input',
                  output_schema_checksum='output', total_commits=0, analyzed_commits=0,
                  analysis_status='complete', results={})
    token = basic(auth) if auth else None
    with running(app, auth=auth) as (port, log, errors):
        for index, method in enumerate(methods):
            result['analysis_status'] = 'partial' if index else 'complete'
            payload = json.dumps(result, sort_keys=True).encode()
            if auth:
                assert request(port, '/result/1.json', method=method, body=payload)[0] == 401
            code, headers, body = request(port, '/result/1.json', method=method,
                                         authorization=token, body=payload)
            assert code == 200 and headers['Content-Type'] == 'application/json'
            assert json.loads(body) == {'status': 'ok'}
            assert request(port, '/result/1.json', authorization=token)[2] == payload
            assert request(port, '/result/1.json', method=method,
                           authorization=token, body=b'{}')[0] == 400
            assert request(port, '/result/1.json', authorization=token)[2] == payload
            assert request(port, '/result/999.json', method=method,
                           authorization=token, body=payload)[0] == 404
        code, _, exported = request(port, '/export', authorization=token)
        assert code == 200
        with zipfile.ZipFile(io.BytesIO(exported)) as archive:
            assert archive.read('results/1.json') == payload
    for method in methods:
        assert f'method="{method}" path="/result/1.json" status=400' in log.read_text()
    assert log.read_text().count('reason=invalid_result') == 2
    assert not list(Path(str(app) + '.results').glob('.upload-*'))


@pytest.mark.parametrize('method', ['POST', 'PUT'])
@pytest.mark.parametrize('length', [0, 10 * 1024 * 1024 + 1])
def test_both_methods_enforce_body_limits(namespace, method, length):
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.path = '/result/1.json'
    handler.headers = {'Content-Length': str(length)}
    handler.rfile = io.BytesIO()
    errors = []
    handler.send_error = lambda code, message: errors.append(code)
    getattr(handler, 'do_' + method)()
    assert errors == [400]
    assert not Path(namespace['RESULTS']).exists()
