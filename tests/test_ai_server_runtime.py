"""Embedded server CLI, access logging, authentication, and daemon regressions."""
import base64
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
import zipfile

import pytest

from lib.ai_serve_script_gen import _MAIN_SOURCE, generate_ai_serve_script


@pytest.fixture
def app(tmp_path):
    source = b'{"commits": []}'
    manifest = {'run_id': 'test-run', 'chunks': {'1.json': hashlib.sha256(source).hexdigest()},
                'input_schema_checksum': 'input', 'output_schema_checksum': 'output'}
    required = ['schema_version', 'run_id', 'source_chunk', 'input_checksum',
                'input_schema_checksum', 'output_schema_checksum', 'total_commits',
                'analyzed_commits', 'analysis_status', 'results']
    schema = {'required': required, 'properties': {'results': {'additionalProperties':
              {'properties': {}}}}}
    (tmp_path / 'ai_analysis_input').mkdir()
    (tmp_path / 'ai_analysis_input' / '1.json').write_bytes(source)
    for name, value in [('ai_analysis_bundle_manifest.json', manifest),
                        ('ai_analysis_input_schema.json', {}),
                        ('ai_analysis_result_schema.json', schema)]:
        (tmp_path / name).write_text(json.dumps(value), encoding='utf-8')
    (tmp_path / 'ai_analysis_prompt.md').write_text('Analyze commits', encoding='utf-8')
    result = tmp_path / 'serve_ai.pyz'
    generate_ai_serve_script(str(tmp_path), str(result))
    return result


@pytest.fixture
def namespace(app, monkeypatch):
    monkeypatch.setattr(sys, 'argv', [str(app)])
    values = {'__name__': 'embedded_server_test'}
    exec(compile(_MAIN_SOURCE, '__main__.py', 'exec'), values)
    yield values
    values['ARCHIVE'].close()


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('Timed out waiting for server state')


@contextmanager
def running(app, flag='--no-daemon', auth=None, daemon=False):
    log = app.parent / 'access.log'
    stderr = app.parent / 'stderr.log'
    args = [sys.executable, str(app), '--log-file', str(log), '0', '127.0.0.1']
    if not daemon:
        args.append(flag)
    if auth is not None:
        args += ['--auth', auth]
    proc = None
    pid = None
    with stderr.open('wb') as errors:
        try:
            if daemon:
                result = subprocess.run(args, stdout=subprocess.PIPE, stderr=errors, timeout=5)
                assert result.returncode == 0
                match = re.search(rb'PID=(\d+) address=127[.]0[.]0[.]1:(\d+)', result.stdout)
                assert match, result.stdout
                pid = int(match[1])
            else:
                proc = subprocess.Popen(args, stdout=errors, stderr=errors)
            wait_until(lambda: log.exists() and 'SERVER start ' in log.read_text())
            match = re.findall(r'SERVER start pid=\d+ address=127[.]0[.]0[.]1:(\d+)', log.read_text())
            assert match
            yield int(match[-1]), log, stderr
        finally:
            if pid is not None:
                os.kill(pid, signal.SIGTERM)
                wait_until(lambda: 'SERVER stop pid=%s' % pid in log.read_text())
            if proc is not None:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    assert proc.wait(timeout=5) == 0
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                    raise


def request(port, path, method='GET', authorization=None, body=None):
    headers = {} if authorization is None else {'Authorization': authorization}
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def basic(value):
    return 'Basic ' + base64.b64encode(value.encode('utf-8')).decode('ascii')


def access_lines(log):
    return [line for line in log.read_text().splitlines() if ' SERVER ' not in line]


def test_defaults(namespace):
    args = namespace['build_parser']().parse_args([])
    assert (args.host, args.port, args.no_daemon) == ('0.0.0.0', 8000, False)
    assert args.log_file == '/var/log/kcommit-analyze-ai-server.log'
    assert args.auth is None


@pytest.mark.parametrize('flag', ['-d', '--debug', '--no-daemon'])
def test_foreground_aliases(app, namespace, flag):
    assert namespace['build_parser']().parse_args([flag]).no_daemon
    with running(app, flag=flag) as (port, log, stderr):
        assert request(port, '/chunks')[0] == 200
        assert len(access_lines(log)) == 1
        assert 'WARNING: authentication disabled' in stderr.read_text()
        assert '"GET" "/chunks" 200' in stderr.read_text()
    assert 'SERVER stop' in log.read_text()


@pytest.mark.parametrize('value', ['', 'user', ':password', 'user:', 'user:bad\nvalue'])
def test_invalid_auth_rejected(namespace, value):
    with pytest.raises(SystemExit) as exc:
        namespace['auth_credentials'](namespace['build_parser'](), value)
    assert exc.value.code == 2


def test_colon_password(namespace):
    assert namespace['auth_credentials'](namespace['build_parser'](), 'user:pass:word') == b'user:pass:word'


def test_all_endpoints_require_auth_and_log_once(app):
    credentials = 'test-user:secret:password'
    cases = [('GET', '/prompt'), ('GET', '/schema/input'), ('GET', '/schema/output'),
             ('GET', '/chunks'), ('GET', '/chunk/1.json'), ('GET', '/result/1.json'),
             ('PUT', '/result/1.json'), ('GET', '/export'), ('HEAD', '/chunks'),
             ('POST', '/chunks')]
    with running(app, auth=credentials) as (port, log, stderr):
        for method, path in cases:
            status, headers, body = request(port, path, method=method)
            assert status == 401
            assert headers['WWW-Authenticate'].startswith('Basic ')
            assert body == b''
        for header in [basic('test-user:wrong'), 'Basic !!!', 'Bearer token', 'Basic']:
            assert request(port, '/chunks', authorization=header)[0] == 401
        assert request(port, '/chunks?token=do-not-log', authorization=basic(credentials))[0] == 200
        assert request(port, '/missing', authorization=basic(credentials))[0] == 404
        assert request(port, '/result/1.json', method='PUT', body=b'{}',
                       authorization=basic(credentials))[0] == 400
        assert len(access_lines(log)) == len(cases) + 7
        assert not Path(str(app) + '.results').exists()
        text = log.read_text() + stderr.read_text()
        for secret in [credentials, basic(credentials), 'do-not-log', 'token=']:
            assert secret not in text


def test_valid_upload_and_export(app):
    with zipfile.ZipFile(app) as archive:
        manifest = json.loads(archive.read('ai_analysis_bundle_manifest.json'))
    payload = json.dumps({'schema_version': '1.0', 'run_id': 'test-run',
        'source_chunk': '1.json', 'input_checksum': manifest['chunks']['1.json'],
        'input_schema_checksum': 'input', 'output_schema_checksum': 'output',
        'total_commits': 0, 'analyzed_commits': 0, 'analysis_status': 'complete', 'results': {}}).encode()
    with running(app, auth='user:password') as (port, log, stderr):
        authorization = basic('user:password')
        assert request(port, '/result/1.json', method='PUT', body=payload,
                       authorization=authorization)[0] == 200
        assert request(port, '/result/1.json', authorization=authorization)[2] == payload
        assert request(port, '/export', authorization=authorization)[0] == 200
        assert len(access_lines(log)) == 3


def test_log_appends(app):
    log = app.parent / 'access.log'
    log.write_text('sentinel\n')
    with running(app) as (port, log, stderr):
        assert request(port, '/chunks')[0] == 200
    assert log.read_text().startswith('sentinel\n')


def test_log_control_characters_escaped(namespace):
    records = []
    class Logger:
        def info(self, fmt, *args):
            records.append(fmt % args)
    handler = object.__new__(namespace['Handler'])
    handler.path = '/evil\nline?password=secret'
    handler.command = 'GET'
    handler.client_address = ('127.0.0.1', 1234)
    handler.server = type('Server', (), {'access_logger': Logger()})()
    handler.log_request(400)
    assert len(records) == 1
    assert '\n' not in records[0]
    assert 'secret' not in records[0]
    assert '\\n' in records[0]


def test_startup_failures_do_not_detach(app):
    missing = app.parent / 'missing' / 'server.log'
    result = subprocess.run([sys.executable, str(app), '--log-file', str(missing)],
                            capture_output=True, timeout=5)
    assert result.returncode == 2
    assert b'choose a writable location with --log-file' in result.stderr
    assert b'Background server PID=' not in result.stdout
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        sock.listen()
        port = sock.getsockname()[1]
        result = subprocess.run([sys.executable, str(app), '--log-file',
                                 str(app.parent / 'bind.log'), str(port), '127.0.0.1'],
                                capture_output=True, timeout=5)
    assert result.returncode == 1
    assert b'Server startup failed:' in result.stderr
    assert b'Background server PID=' not in result.stdout


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='Unix daemon lifecycle')
def test_daemon_lifecycle(app):
    with running(app, daemon=True, auth='user:password') as (port, log, stderr):
        assert request(port, '/chunks', authorization=basic('user:password'))[0] == 200
        assert len(access_lines(log)) == 1
    with socket.socket() as sock:
        wait_until(lambda: sock.connect_ex(('127.0.0.1', port)) != 0)
