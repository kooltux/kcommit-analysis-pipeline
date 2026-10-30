"""--save-posts keeps the latest POST body and a Markdown exchange report per path."""
import hashlib
import http.client
import subprocess
import sys
from pathlib import Path

import pytest

from lib.ai_contract import encode
from test_ai_package_server import app, package, workflow
from test_ai_preparation import snapshots
from test_ai_server_runtime import basic, namespace, request, running, wait_until

SECTIONS = ['## Request context', '## Request headers', '## Response headers', '## Response body']


def debug_dir(app):
    return app.with_name(app.name + '.debug')


def report(path):
    path = Path(str(path) + '.md')
    wait_until(path.exists)
    return path.read_text(encoding='utf-8')


def post_raw(port, path, body, content_type, token=None):
    headers = {'Content-Type': content_type}
    if token:
        headers['Authorization'] = token
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request('POST', path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_fenced_uses_longer_fence_than_content(namespace):
    text = namespace['fenced']('a ``` b ````` c', 'json')
    assert text.startswith('``````json\n') and text.endswith('\n``````\n')
    assert namespace['fenced']('plain').startswith('```\nplain')


def test_no_directory_without_flag(app, workflow):
    name, documents = workflow
    with running(app) as (port, log, errors):
        response = request(port, '/validate/workflow/' + name, method='POST', body=encode(documents))
        assert response[0] == 200
    assert not debug_dir(app).exists()


@pytest.mark.parametrize('daemon', [False, True])
def test_valid_validate_posts_are_saved(app, workflow, daemon):
    name, documents = workflow
    with running(app, daemon=daemon, extra=('-s',)) as (port, log, errors):
        body = encode(documents['analyst'])
        assert request(port, '/validate/role/analyst/' + name, method='POST', body=body)[0] == 200
        text = report(debug_dir(app) / 'validate/ok/role/analyst' / name)
        assert (debug_dir(app) / 'validate/ok/role/analyst' / name).read_bytes() == body
        assert [text.index(section) for section in SECTIONS] == sorted(text.index(s) for s in SECTIONS)
        assert 'Outcome: ok (HTTP 200)' in text and '"status": "valid"' in text
        assert hashlib.sha256(body).hexdigest() in text
        body = encode(documents)
        assert request(port, '/validate/workflow/' + name, method='POST', body=body)[0] == 200
        report(debug_dir(app) / 'validate/ok/workflow' / name)
        assert (debug_dir(app) / 'validate/ok/workflow' / name).read_bytes() == body
    assert not app.with_name(app.name + '.results').exists()


def test_invalid_validate_post_is_saved_and_latest_wins(app, workflow):
    name, documents = workflow
    target = debug_dir(app) / 'validate/error/workflow' / name
    with running(app, extra=('-s',)) as (port, log, errors):
        assert request(port, '/validate/workflow/' + name, method='POST', body=b'{}')[0] == 400
        text = report(target)
        assert target.read_bytes() == b'{}' and 'Outcome: error (HTTP 400)' in text
        assert 'HTTP/1.0 400' in text and 'invalid_request' in text
        assert request(port, '/validate/workflow/' + name, method='POST', body=b'{"a": 1}')[0] == 400
        wait_until(lambda: target.read_bytes() == b'{"a": 1}')
        assert not (debug_dir(app) / 'validate/ok').exists()


def test_valid_result_saves_report_only_and_matches_stored_result(app, workflow):
    name, documents = workflow
    body = encode(documents['result'])
    target = debug_dir(app) / 'result/ok' / name
    with running(app, extra=('-s',)) as (port, log, errors):
        assert request(port, '/result/' + name, method='POST', body=body)[0] == 200
        text = report(target)
    stored = app.with_name(app.name + '.results') / name
    assert stored.read_bytes() == body and not target.exists()
    assert 'not duplicated; byte-identical' in text
    assert hashlib.sha256(stored.read_bytes()).hexdigest() in text


def test_invalid_result_saves_body_and_stores_nothing(app, workflow):
    name, documents = workflow
    target = debug_dir(app) / 'result/error' / name
    with running(app, extra=('-s',)) as (port, log, errors):
        assert request(port, '/result/' + name, method='POST', body=b'{"x": 1}')[0] == 400
        text = report(target)
    assert target.read_bytes() == b'{"x": 1}' and 'Outcome: error (HTTP 400)' in text
    assert not app.with_name(app.name + '.results').exists()


def test_unread_body_is_reported_and_stale_body_removed(app, workflow):
    name, documents = workflow
    target = debug_dir(app) / 'validate/error/workflow' / name
    with running(app, extra=('-s',)) as (port, log, errors):
        assert request(port, '/validate/workflow/' + name, method='POST', body=b'{}')[0] == 400
        report(target)
        assert target.exists()
        assert post_raw(port, '/validate/workflow/' + name, b'x', 'text/plain')[0] == 400
        marker = Path(str(target) + '.md')
        wait_until(lambda: not target.exists() and 'not read; the request was rejected' in marker.read_text())


def test_credentials_are_redacted(app, workflow):
    name, documents = workflow
    auth = 'reviewer:secret'
    with running(app, auth=auth, extra=('-s',)) as (port, log, errors):
        response = request(port, '/validate/workflow/' + name, method='POST',
                           body=encode(documents), authorization=basic(auth))
        assert response[0] == 200
        text = report(debug_dir(app) / 'validate/ok/workflow' / name)
    assert 'Authorization: Basic ***' in text
    assert 'secret' not in text and basic(auth).split()[1] not in text


def test_rejected_and_unknown_requests_are_not_saved(app, workflow):
    name, documents = workflow
    with running(app, auth='reviewer:secret', extra=('-s',)) as (port, log, errors):
        token = basic('reviewer:secret')
        assert request(port, '/validate/workflow/' + name, method='POST', body=b'{}')[0] == 401
        assert request(port, '/validate/workflow/batch_001/999.json', method='POST',
                       body=b'{}', authorization=token)[0] == 404
        assert request(port, '/validate/role/unknown/' + name, method='POST',
                       body=b'{}', authorization=token)[0] == 404
        assert request(port, '/validate/workflow/' + name, authorization=token)[0] == 405
        assert request(port, '/chunks', authorization=token)[0] == 200
    assert list(debug_dir(app).rglob('*')) == []


def test_permissions_are_private(app, workflow):
    name, documents = workflow
    with running(app, extra=('-s',)) as (port, log, errors):
        assert request(port, '/validate/workflow/' + name, method='POST', body=b'{}')[0] == 400
        report(debug_dir(app) / 'validate/error/workflow' / name)
    assert debug_dir(app).stat().st_mode & 0o777 == 0o700
    files = [path for path in debug_dir(app).rglob('*') if path.is_file()]
    assert len(files) == 2 and all(path.stat().st_mode & 0o777 == 0o600 for path in files)


def test_write_failure_does_not_affect_response(app, workflow):
    name, documents = workflow
    with running(app, extra=('-s',)) as (port, log, errors):
        (debug_dir(app) / 'validate').write_text('blocked')
        response = request(port, '/validate/workflow/' + name, method='POST', body=encode(documents))
        assert response[0] == 200
        wait_until(lambda: 'save_posts failed' in log.read_text())


def test_unwritable_directory_stops_startup(app):
    debug_dir(app).write_text('not a directory')
    result = subprocess.run([sys.executable, str(app), '0', '127.0.0.1', '-d', '-s'],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'Cannot create the --save-posts directory' in result.stderr
