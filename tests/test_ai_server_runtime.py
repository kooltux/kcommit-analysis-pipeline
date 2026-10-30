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

from lib.ai_serve_script_gen import _MAIN_SOURCE
from lib.ai_assets import load_contract
from lib.ai_preparation import build_package
from lib.ai_package_server import generate_ai_package_server
from lib.manifest import VERSION


@pytest.fixture
def app(tmp_path):
    samples = Path(__file__).resolve().parents[1] / 'configs' / 'ai'
    snapshots = load_contract({'ai': {'prompts_dir': str(samples / 'prompts'),
                                     'schemas_dir': str(samples / 'schemas')}})['files']
    package = build_package([], {}, snapshots, VERSION)
    result = tmp_path / 'serve_ai.pyz'
    generate_ai_package_server(package, b'# Server purpose\n', result)
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
def running(app, flag='--no-daemon', auth=None, daemon=False, file_logging=True):
    stderr = app.parent / 'stderr.log'
    log = app.parent / 'access.log' if file_logging else stderr
    args = [sys.executable, str(app), '0', '127.0.0.1']
    if file_logging:
        args += ['-l', str(log)]
    if not daemon:
        args.append(flag)
    if auth is not None:
        args += ['--auth', auth]
    proc = None
    pid = None
    with stderr.open('wb') as errors, (app.parent / 'stdout.log').open('wb') as output:
        try:
            if daemon:
                result = subprocess.run(args, stdout=subprocess.PIPE, stderr=errors, timeout=5)
                assert result.returncode == 0
                assert b'url=http://127.0.0.1:' in result.stdout
                match = re.search(rb'PID=(\d+) address=127[.]0[.]0[.]1:(\d+)', result.stdout)
                assert match, result.stdout
                pid = int(match[1])
            else:
                proc = subprocess.Popen(args, stdout=output, stderr=errors)
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


def request(port, path, method='GET', authorization=None, body=None, accept=None):
    headers = {} if authorization is None else {'Authorization': authorization}
    if accept is not None:
        headers['Accept'] = accept
    if body is not None and method == 'POST':
        headers['Content-Type'] = 'application/json'
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


def assert_access_count(log, expected):
    """The server logs a request after sending the response: wait for the line(s)."""
    wait_until(lambda: len(access_lines(log)) >= expected)
    assert len(access_lines(log)) == expected


def test_defaults(namespace):
    args = namespace['build_parser']().parse_args([])
    assert (args.host, args.port, args.no_daemon) == ('127.0.0.1', 8000, False)
    assert args.log_file is None
    assert args.auth is None


@pytest.mark.parametrize('flag', ['-d', '--debug', '--no-daemon'])
def test_foreground_aliases(app, namespace, flag):
    assert namespace['build_parser']().parse_args([flag]).no_daemon
    with running(app, flag=flag) as (port, log, stderr):
        assert request(port, '/chunks')[0] == 200
        assert_access_count(log, 1)
        assert 'WARNING: authentication disabled' in log.read_text()
        assert stderr.read_text() == ''
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
    cases = [('GET', '/prompt/analyst'), ('GET', '/schema/input'), ('GET', '/schema/result'),
             ('GET', '/chunks'), ('GET', '/chunk/batch_001/001.json'), ('GET', '/result/batch_001/001.json'),
             ('POST', '/result/batch_001/001.json'), ('GET', '/export'), ('HEAD', '/chunks'),
             ('POST', '/chunks')]
    with running(app, auth=credentials) as (port, log, stderr):
        for method, path in cases:
            status, headers, body = request(port, path, method=method)
            assert status == 401
            if method == 'HEAD':
                assert body == b''
            else:
                assert json.loads(body)['error']['code'] == 'authentication_failed'
        for header in [basic('test-user:wrong'), 'Basic !!!', 'Bearer token', 'Basic']:
            assert request(port, '/chunks', authorization=header)[0] == 401
        assert request(port, '/chunks?limit=1', authorization=basic(credentials))[0] == 200
        assert request(port, '/chunks?token=do-not-log', authorization=basic(credentials))[0] == 400
        assert request(port, '/missing', authorization=basic(credentials))[0] == 404
        assert request(port, '/result/batch_001/001.json', method='POST', body=b'{}',
                       authorization=basic(credentials))[0] == 400
        assert_access_count(log, len(cases) + 8)
        assert not Path(str(app) + '.results').exists()
        text = log.read_text() + stderr.read_text()
        for secret in [credentials, basic(credentials), 'do-not-log', 'token=']:
            assert secret not in text


def test_valid_upload_and_export(app):
    with zipfile.ZipFile(app) as archive:
        manifest = json.loads(archive.read('ai_analysis_bundle_manifest.json'))
    payload = json.dumps({'schema_version': '1.0', 'run_id': manifest['run_id'],
        'source_chunk': 'batch_001/001.json', 'input_checksum': manifest['chunks']['batch_001/001.json'],
        'input_schema_checksum': manifest['input_schema_checksum'], 'output_schema_checksum': manifest['output_schema_checksum'],
        'total_commits': 0, 'analyzed_commits': 0, 'analysis_status': 'complete', 'results': {}}).encode()
    with running(app, auth='user:password') as (port, log, stderr):
        authorization = basic('user:password')
        assert request(port, '/result/batch_001/001.json', method='POST', body=payload,
                       authorization=authorization)[0] == 200
        assert request(port, '/result/batch_001/001.json', authorization=authorization)[2] == payload
        assert request(port, '/export', authorization=authorization)[0] == 200
        assert_access_count(log, 3)


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
        assert_access_count(log, 1)
    with socket.socket() as sock:
        wait_until(lambda: sock.connect_ex(('127.0.0.1', port)) != 0)


@pytest.mark.parametrize('auth', [None, 'user:password'])
def test_front_page_routes(app, auth):
    with running(app, auth=auth) as (port, log, stderr):
        path = '/'
        if auth:
            status, headers, body = request(port, path)
            assert status == 401 and headers['WWW-Authenticate'].startswith('Basic ')
        status, headers, body = request(port, path,
            authorization=basic(auth) if auth else None)
        assert status == 200
        assert headers['Content-Type'] == 'text/markdown; charset=utf-8'
        assert body == b'# Server purpose\n'
        assert_access_count(log, 2 if auth else 1)


@pytest.mark.parametrize('flag', ['-d', '--debug', '--no-daemon'])
def test_foreground_without_file_uses_only_stderr(app, flag):
    with running(app, flag=flag, file_logging=False) as (port, log, stderr):
        assert request(port, '/chunks')[0] == 200
        assert log == stderr
        assert_access_count(log, 1)
        assert 'WARNING: authentication disabled' in stderr.read_text()
        assert not (app.parent / 'access.log').exists()


def test_daemon_requires_explicit_log_file(app):
    result = subprocess.run([sys.executable, str(app)], capture_output=True, timeout=5)
    assert result.returncode == 2
    assert b'Daemon mode requires -l/--log-file PATH' in result.stderr
    assert b'Background server PID=' not in result.stdout


@pytest.mark.parametrize('option', ['-l', '--log-file'])
def test_log_option_aliases(namespace, option):
    args = namespace['build_parser']().parse_args(['-d', option, 'server.log'])
    assert args.log_file == 'server.log'


def test_foreground_bad_log_fails_without_fallback(app):
    result = subprocess.run([sys.executable, str(app), '-d', '-l',
                             str(app.parent / 'missing' / 'server.log')],
                            capture_output=True, timeout=5)
    assert result.returncode == 2
    assert b'Cannot open log file' in result.stderr
    assert b'SERVER start' not in result.stderr
    assert b'AI server started' not in result.stdout


@pytest.mark.parametrize('file_logging', [False, True])
def test_foreground_stdout_summary(app, file_logging):
    with running(app, file_logging=file_logging, auth='user:secret') as (port, log, stderr):
        summary = (app.parent / 'stdout.log').read_text()
        assert 'started in foreground (debug mode)' in summary
        assert f'URL=http://127.0.0.1:{port}/' in summary
        assert ('logs=' + (str(log) if file_logging else 'stderr')) in summary
        assert 'user:secret' not in summary
        if file_logging:
            assert stderr.read_text() == ''


def test_wildcard_connection_url(namespace):
    assert namespace['connection_url']('0.0.0.0', 12345) == 'http://127.0.0.1:12345/'


def test_request_completion_logs(app):
    with running(app, auth='user:secret') as (port, log, stderr):
        token = basic('user:secret')
        assert request(port, '/chunks?limit=1', authorization=token)[0] == 200
        assert request(port, '/chunks?secret=hidden', authorization=token)[0] == 400
        assert request(port, '/chunks')[0] == 401
        assert request(port, '/missing', authorization=token)[0] == 404
        assert request(port, '/chunks', method='DELETE', authorization=token)[0] == 501
        assert request(port, '/result/batch_001/001.json', method='POST', body=b'{}', authorization=token)[0] == 400
        assert_access_count(log, 6)
        lines = access_lines(log)
        for status, reason, line in zip([200, 400, 401, 404, 501, 400],
                ['ok', 'malformed_request', 'authentication_failed', 'not_found', 'unsupported_method', 'invalid_result'], lines):
            assert f'status={status}' in line
            assert f'reason={reason}' in line
            assert re.search(r'duration_ms=[0-9]+', line)
        assert 'hidden' not in log.read_text()
        assert 'user:secret' not in log.read_text()


@pytest.mark.parametrize('failure, reason', [('timeout', 'timeout'),
    ('disconnect', 'client_disconnected'), ('internal', 'internal_error')])
def test_exception_logs_once(namespace, monkeypatch, failure, reason):
    records = []
    class Logger:
        def info(self, fmt, *args):
            records.append(fmt % args)
    handler = object.__new__(namespace['Handler'])
    handler.client_address = ('127.0.0.1', 1234)
    handler.server = type('Server', (), {'access_logger': Logger()})()
    def perform(self):
        self.raw_requestline = b'GET /chunks HTTP/1.0'
        self.command = 'GET'
        self.path = '/chunks'
        if failure == 'timeout':
            self.log_message('Request timed out: %r', TimeoutError())
        elif failure == 'disconnect':
            raise BrokenPipeError()
        else:
            raise RuntimeError('sensitive exception text')
    monkeypatch.setattr(namespace['http'].server.BaseHTTPRequestHandler, 'handle_one_request', perform)
    handler.send_error = lambda code, message: handler.log_request(code)
    handler.handle_one_request()
    assert len(records) == 1
    assert 'reason=' + reason in records[0]
    assert 'sensitive' not in records[0]


def test_internal_error_returns_500_and_logs_once(app):
    results = Path(str(app) + '.results')
    with zipfile.ZipFile(app) as archive:
        name = next(iter(json.loads(archive.read('ai_analysis_bundle_manifest.json'))['chunks']))
    target = results / name
    target.parent.mkdir(parents=True)
    target.write_text('invalid JSON')
    with running(app) as (port, log, stderr):
        assert request(port, '/export')[0] == 500
        wait_until(lambda: len(access_lines(log)) == 1)
        assert 'reason=internal_error' in access_lines(log)[0]


def test_malformed_request_logged_once(app):
    with running(app) as (port, log, stderr):
        with socket.create_connection(('127.0.0.1', port), timeout=3) as sock:
            sock.sendall(b'GET / HTTP/not-a-version\r\n\r\n')
            while sock.recv(4096):
                pass
        wait_until(lambda: len(access_lines(log)) == 1)
        assert 'status=400' in access_lines(log)[0]
        assert 'reason=malformed_request' in access_lines(log)[0]
