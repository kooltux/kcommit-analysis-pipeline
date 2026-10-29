"""POST validates and replaces results; removed PUT cannot mutate stored data."""
import io
import json
from pathlib import Path
import zipfile
from email.message import Message

import pytest
from test_ai_server_runtime import app, namespace, basic, request, running


def test_only_post_is_registered_for_upload(namespace):
    routes = [r for r in namespace['ROUTES'] if r['path'] == '/result/<name>'
              and r['method'] in ('POST', 'PUT')]
    assert len(routes) == 1
    assert routes[0]['method'] == 'POST'


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_post_replaces_validates_and_exports(app, auth):
    with zipfile.ZipFile(app) as archive:
        manifest = json.loads(archive.read('ai_analysis_bundle_manifest.json'))
        name = next(iter(manifest['chunks']))
        chunk = json.loads(archive.read('ai_analysis_input/' + name))
    path = '/result/' + name
    result = dict(schema_version='1.0', run_id=manifest['run_id'], source_chunk=name,
                  input_checksum=manifest['chunks'][name],
                  input_schema_checksum=manifest['input_schema_checksum'],
                  output_schema_checksum=manifest['output_schema_checksum'],
                  total_commits=len(chunk['commits']), analyzed_commits=0,
                  analysis_status='complete', results={})
    token = basic(auth) if auth else None
    with running(app, auth=auth) as (port, log, errors):
        for index in range(2):
            result['analysis_status'] = 'partial' if index or chunk['commits'] else 'complete'
            payload = json.dumps(result, sort_keys=True).encode()
            if auth:
                assert request(port, path, method='POST', body=payload)[0] == 401
            code, headers, body = request(port, path, method='POST',
                                         authorization=token, body=payload)
            assert code == 200 and headers['Content-Type'] == 'application/json'
            assert json.loads(body) == {'status': 'ok'}
            assert request(port, path, authorization=token)[2] == payload
            assert request(port, path, method='POST',
                           authorization=token, body=b'{}')[0] == 400
            assert request(port, path, authorization=token)[2] == payload
            code, headers, body = request(port, path, method='PUT', authorization=token, body=b'{}')
            assert code == 405 and headers['Allow'] == 'GET, POST'
            assert json.loads(body)['error']['code'] == 'method_not_allowed'
            assert request(port, '/result/999.json', method='POST',
                           authorization=token, body=payload)[0] == 404
        code, _, exported = request(port, '/export', authorization=token)
        assert code == 200
        with zipfile.ZipFile(io.BytesIO(exported)) as archive:
            assert archive.read('results/' + name) == payload
    assert log.read_text().count(f'method="POST" path="{path}" status=400') == 2
    assert log.read_text().count('reason=invalid_result') == 2
    assert not list(Path(str(app) + '.results').rglob('.upload-*'))


@pytest.mark.parametrize('length', [0, 10 * 1024 * 1024 + 1])
def test_post_enforces_body_limits(namespace, length):
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.path = '/result/' + next(iter(namespace['NAMES']))
    handler.headers = Message()
    handler.headers['Content-Length'] = str(length)
    handler.headers['Content-Type'] = 'application/json'
    handler.rfile = io.BytesIO()
    errors = []
    handler.send_error = lambda code, message=None, explain=None: errors.append((code, message))
    handler.do_POST()
    assert len(errors) == 1
    assert 'size limits' in errors[0][1]
    assert errors[0][0] == 400
    assert not Path(namespace['RESULTS']).exists()
