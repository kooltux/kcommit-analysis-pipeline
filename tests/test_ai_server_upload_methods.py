"""Canonical publication is POST-only and invalid methods cannot change findings."""
import io
import json
from pathlib import Path
from email.message import Message
import pytest
from test_ai_package_server import app, package, snapshots
from test_ai_server_runtime import namespace, basic, request, running
from ai_http_helpers import record_url, workflow_paths
from test_ai_versioned_runtime import contributions, post

def test_only_post_is_registered_for_upload(namespace):
    for path in ('/v1/result', '/v2/result/<group_id>'):
        assert {r['method'] for r in namespace['ROUTES'] if r['path'] == path} == {'POST'}

@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_post_replaces_validates_and_exports(app, package, auth):
    token = basic(auth) if auth else None
    with running(app, auth=auth) as (port, log, errors):
        if auth:
            assert post(port, '/v1/result', contributions(package))[0] == 401
        assert post(port, '/v1/result', contributions(package), token)[0] == 200
        before = request(port, '/v1/result/' + 'a' * 40, authorization=token)[2]
        for prefix in ('/v1', '/v2'):
            _, submission = workflow_paths(port, prefix, token=token)
            assert post(port, submission, {}, token)[0] == 400
            code, headers, body = request(port, submission, method='PUT', body=b'{}', authorization=token)
            assert code == 405 and headers['Allow'] == 'POST'
            status, _, raw = request(port, record_url(prefix, 'a' * 40), authorization=token)
            assert status == 200 and raw == before
            assert request(port, prefix + '/export', authorization=token)[0] == 200
    assert not list(Path(str(app) + '.results').rglob('.result-*'))

@pytest.mark.parametrize('length', [0, 10 * 1024 * 1024 + 1])
def test_post_enforces_body_limits(namespace, length):
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.path = '/v1/result'
    handler.headers = Message()
    handler.headers['Content-Length'] = str(length)
    handler.headers['Content-Type'] = 'application/json'
    handler.rfile = io.BytesIO()
    errors = []
    handler.send_error = lambda code, message=None, explain=None: errors.append((code, message))
    handler.do_POST()
    assert len(errors) == 1 and errors[0][0] == 400
    assert isinstance(errors[0][1], ValueError) and 'size limits' in str(errors[0][1])
    assert not Path(namespace['RESULTS']).exists()
