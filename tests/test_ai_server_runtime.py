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
    (tmp_path / 'ai_server_front_page.md').write_text('# Server purpose\n', encoding='utf-8')
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
    assert (args.host, args.port, args.no_daemon) == ('127.0.0.1', 8000, False)
    assert args.log_file is None
    assert args.auth is None


@pytest.mark.parametrize('flag', ['-d', '--debug', '--no-daemon'])
def test_foreground_aliases(app, namespace, flag):
    assert namespace['build_parser']().parse_args([flag]).no_daemon
    with running(app, flag=flag) as (port, log, stderr):
        assert request(port, '/chunks')[0] == 200
        assert len(access_lines(log)) == 1
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


@pytest.mark.parametrize('auth', [None, 'user:password'])
def test_front_page_routes(app, auth):
    with running(app, auth=auth) as (port, log, stderr):
        for path in ['/', '/README.md']:
            if auth:
                assert request(port, path)[0] == 401
            status, headers, body = request(port, path,
                authorization=basic(auth) if auth else None)
            assert status == 200
            assert headers['Content-Type'] == 'text/markdown; charset=utf-8'
            assert body == b'# Server purpose\n'
        assert len(access_lines(log)) == (4 if auth else 2)


@pytest.mark.parametrize('flag', ['-d', '--debug', '--no-daemon'])
def test_foreground_without_file_uses_only_stderr(app, flag):
    with running(app, flag=flag, file_logging=False) as (port, log, stderr):
        assert request(port, '/chunks')[0] == 200
        assert log == stderr
        assert len(access_lines(log)) == 1
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
        assert request(port, '/chunks?secret=hidden', authorization=token)[0] == 200
        assert request(port, '/chunks')[0] == 401
        assert request(port, '/missing', authorization=token)[0] == 404
        assert request(port, '/chunks', method='POST', authorization=token)[0] == 501
        assert request(port, '/result/1.json', method='PUT', body=b'{}', authorization=token)[0] == 400
        wait_until(lambda: len(access_lines(log)) == 5)
        lines = access_lines(log)
        for status, reason, line in zip([200, 401, 404, 501, 400],
                ['ok', 'authentication_failed', 'not_found', 'unsupported_method', 'invalid_result'], lines):
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
    results.mkdir()
    (results / '1.json').write_text('invalid JSON')
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
