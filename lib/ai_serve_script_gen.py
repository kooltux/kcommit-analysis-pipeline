"""Generate a self-contained AI exchange zipapp with validated result uploads."""
import io
import json
from lib.ai_contract import NAME
import os
import zipapp
import zipfile

TOOL_MANIFEST_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'MANIFEST.json')

_MAIN_SOURCE = '''\
import argparse
import base64
import binascii
import hmac
import logging
import signal
import urllib.parse
import time
import http.server
import io
import json
import os
import re
import sys
import tempfile
import zipfile
import hashlib

ARCHIVE = zipfile.ZipFile(sys.argv[0], 'r')
MANIFEST = json.loads(ARCHIVE.read('ai_analysis_bundle_manifest.json'))
SERVER_VERSION = json.loads(ARCHIVE.read('ai_server_version.json'))
SCHEMA = json.loads(ARCHIVE.read('ai_analysis_result_schema.json'))
NAMES = MANIFEST['chunks']
SAFE = re.compile(r'^(?:batch_[0-9]{3,}/)?[0-9]+[.]json$')
BATCHES = {batch['batch_id']: batch for batch in MANIFEST.get('batches', [])}
RESULTS = os.path.abspath(sys.argv[0]) + '.results'

def checksum(data):
    return hashlib.sha256(data).hexdigest()

def validate(name, value):
    if name not in NAMES or not SAFE.fullmatch(name):
        raise ValueError('Unknown chunk')
    source = ARCHIVE.read('ai_analysis_input/' + name)
    if checksum(source) != NAMES[name]:
        raise ValueError('Source chunk checksum mismatch')
    chunk = json.loads(source)
    required = set(SCHEMA['required'])
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('Invalid result envelope')
    for key, expected in (('schema_version', '1.0'), ('run_id', MANIFEST['run_id']),
                          ('source_chunk', name), ('input_checksum', checksum(source)),
                          ('input_schema_checksum', MANIFEST['input_schema_checksum']),
                          ('output_schema_checksum', MANIFEST['output_schema_checksum']),
                          ('total_commits', len(chunk['commits']))):
        if value[key] != expected:
            raise ValueError('Result identity mismatch: ' + key)
    records = value['results']
    allowed = {c['commit'] for c in chunk['commits']}
    if not isinstance(records, dict) or not set(records).issubset(allowed):
        raise ValueError('Unknown result commit')
    if type(value['analyzed_commits']) is not int or value['analyzed_commits'] != len(records):
        raise ValueError('Invalid analyzed count')
    if value['analysis_status'] not in ('complete', 'partial') or (
            value['analysis_status'] == 'complete' and set(records) != allowed):
        raise ValueError('Invalid analysis status or incomplete result')
    specs = SCHEMA['properties']['results']['additionalProperties']['properties']
    for item in records.values():
        if not isinstance(item, dict) or set(item) != set(specs):
            raise ValueError('Invalid result fields')
        for key, spec in specs.items():
            val = item[key]
            if spec['type'] == 'boolean' and type(val) is not bool:
                raise ValueError('Invalid boolean ' + key)
            if spec['type'] == 'string' and (not isinstance(val, str) or
                    ('enum' in spec and val not in spec['enum'])):
                raise ValueError('Invalid string ' + key)
            if spec['type'] == 'array':
                sub = spec['items']
                if not isinstance(val, list) or any(
                        (type(v) is not int if sub['type'] == 'integer' else not isinstance(v, str))
                        or ('enum' in sub and v not in sub['enum'])
                        or ('minimum' in sub and v < sub['minimum'])
                        or ('maximum' in sub and v > sub['maximum'])
                        or ('pattern' in sub and not re.fullmatch(sub['pattern'], v))
                        for v in val):
                    raise ValueError('Invalid array ' + key)
        risks = item.get('ai_risks_if_not_backported')
        if risks is not None and (len(risks) != len(set(risks)) or
                                  ('none' in risks and len(risks) != 1)):
            raise ValueError('Invalid risk combination')
        ids = item.get('ai_cve_ids')
        probabilities = item.get('ai_cve_probabilities')
        if ids is not None and probabilities is not None and len(ids) != len(probabilities):
            raise ValueError('CVE ID and probability counts differ')
    return True

ROUTES = []
MAX_RESULT_BYTES = 10 * 1024 * 1024
LIST_QUERY_PARAMETERS = {
    'limit': {'type': 'integer', 'default': 0, 'minimum': 0,
              'description': 'Maximum returned items; missing, invalid or nonpositive means unlimited. First repeated value wins.'},
    'offset': {'type': 'integer', 'default': 0, 'minimum': 0,
               'description': 'Zero-based number of items to skip; missing, invalid or negative means zero. First repeated value wins.'},
}


def listing_page(target, values):
    """Apply offset before limit without changing order or the source collection."""
    query = urllib.parse.parse_qs(target.partition('?')[2], keep_blank_values=True)
    numbers = {}
    for name, spec in LIST_QUERY_PARAMETERS.items():
        raw = query.get(name, [str(spec['default'])])[0].strip()
        try:
            if not re.fullmatch(r'[+-]?[0-9]+', raw):
                raise ValueError('Not an integer')
            number = int(raw)
            numbers[name] = number if number >= spec['minimum'] else spec['default']
        except ValueError:
            numbers[name] = spec['default']
    offset, limit = numbers['offset'], numbers['limit']
    items = list(values)
    return items[offset:offset + limit if limit else None]




def route(method, path, content_type='application/json', **contract):
    """Register an executable route and its machine-readable contract together."""
    parameters = re.findall(r'<([a-z_]+)>', path)
    pattern = re.escape(path)
    for name in parameters:
        pattern = pattern.replace('<' + name + '>', '(?P<' + name + '>.+)')
    def register(handler):
        if any(item['method'] == method and item['path'] == path for item in ROUTES):
            raise ValueError('Duplicate API route: ' + method + ' ' + path)
        ROUTES.append(dict(contract, method=method, path=path,
                           response_content_type=content_type, parameters=parameters,
                           handler=handler, matcher=re.compile(pattern)))
        return handler
    return register


class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def log_message(self, fmt, *args):
        # Suppress default messages, including duplicate error logging.
        if fmt.startswith('Request timed out:'):
            self._reason = 'timeout'

    def handle_one_request(self):
        self._handling = True
        self._started = time.perf_counter()
        self._status = None
        self._reason = None
        self.raw_requestline = b''
        self.command = None
        self.path = ''
        self.request_version = 'HTTP/1.0'
        try:
            super().handle_one_request()
        except ConnectionError:
            self._reason = 'client_disconnected'
            self.close_connection = True
        except Exception:
            self._reason = 'internal_error'
            self.close_connection = True
            if self._status is None:
                try:
                    self.send_error(500, 'Internal server error')
                except OSError:
                    pass
        finally:
            self._handling = False
            if self.raw_requestline or self._reason:
                self.log_request(self._status if self._status is not None else '-')

    def log_request(self, code='-', size='-'):
        self._status = code
        if getattr(self, '_handling', False):
            return
        path = getattr(self, 'path', '').split('?', 1)[0]
        if path.startswith(('http://', 'https://')):
            try:
                path = urllib.parse.urlsplit(path).path
            except ValueError:
                path = '<invalid-target>'
        method = getattr(self, 'command', None) or '-'
        reasons = {400: 'invalid_result' if method == 'PUT' else 'malformed_request',
                   401: 'authentication_failed', 404: 'not_found', 408: 'timeout',
                   414: 'request_line_too_long', 431: 'headers_too_large',
                   500: 'internal_error', 501: 'unsupported_method'}
        reason = getattr(self, '_reason', None) or reasons.get(code, 'ok')
        now = time.perf_counter()
        duration = max(0, round((now - getattr(self, '_started', now)) * 1000))
        self.server.access_logger.info(
            'client=%s method=%s path=%s status=%s duration_ms=%s reason=%s',
            self.client_address[0], json.dumps(method, ensure_ascii=True),
            json.dumps(path, ensure_ascii=True), code, duration, reason)

    def parse_request(self):
        if not super().parse_request():
            return False
        expected = self.server.auth_credentials
        if expected is None:
            return True
        supplied = self.headers.get_all('Authorization', [])
        valid = False
        if len(supplied) == 1:
            parts = supplied[0].split()
            if len(parts) == 2 and parts[0].lower() == 'basic':
                try:
                    decoded = base64.b64decode(parts[1], validate=True)
                    valid = hmac.compare_digest(decoded, expected)
                except (ValueError, binascii.Error):
                    pass
        if not valid:
            self.close_connection = True
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="kcommit-analyze-ai", charset="UTF-8"')
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            self.end_headers()
        return valid

    def send_bytes(self, data, kind=None):
        kind = kind or getattr(self, 'active_route', {}).get('response_content_type', 'application/json')
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.dispatch('GET')

    def do_PUT(self):
        self.dispatch('PUT')

    def dispatch(self, method):
        path = self.path.split('?', 1)[0]
        for item in ROUTES:
            match = item['matcher'].fullmatch(path)
            if item['method'] == method and match:
                self.active_route = item
                item['handler'](self, **match.groupdict())
                return
        self.send_error(404)

    @route('GET', '/api')
    def api(self):
        """Describe routes from the executable registry, not a packaged document."""
        routes = []
        for item in ROUTES:
            if not callable(getattr(type(self), 'do_' + item['method'], None)):
                continue
            entry = {key: value for key, value in item.items() if key not in ('handler', 'matcher')}
            entry['description'] = (item['handler'].__doc__ or '').strip()
            routes.append(entry)
        required = self.server.auth_credentials is not None
        self.send_bytes(json.dumps({'run_id': MANIFEST['run_id'], 'routes': routes,
            'authentication': {'required': required, 'scheme': 'Basic' if required else None}},
            sort_keys=True).encode())

    @route('GET', '/api/version')
    def version(self):
        """Report the tool manifest version captured when this zipapp was generated."""
        self.send_bytes(json.dumps(SERVER_VERSION, sort_keys=True).encode())

    @route('GET', '/', 'text/markdown; charset=utf-8')
    @route('GET', '/README.md', 'text/markdown; charset=utf-8')
    def front_page(self):
        """Read the shared human, AI-client and automation guide."""
        self.send_bytes(ARCHIVE.read('ai_server_front_page.md'))

    @route('GET', '/prompt', 'text/markdown')
    def prompt(self):
        """Read the assessment instructions."""
        self.send_bytes(ARCHIVE.read('ai_analysis_prompt.md'))

    @route('GET', '/schema/input')
    def input_schema(self):
        """Read the authoritative source-chunk JSON Schema."""
        self.send_bytes(ARCHIVE.read('ai_analysis_input_schema.json'))

    @route('GET', '/schema/output')
    def output_schema(self):
        """Read the authoritative result JSON Schema."""
        self.send_bytes(ARCHIVE.read('ai_analysis_result_schema.json'))

    @route('GET', '/batches', query_parameters=LIST_QUERY_PARAMETERS)
    def batches(self):
        """List batch assignments, member chunk paths and discovery URLs."""
        self.send_bytes(json.dumps({'run_id': MANIFEST['run_id'],
            'batch_size': MANIFEST.get('batch_size'), 'total_batches': len(BATCHES),
            'batches': [dict(batch, url='/batch/' + key)
                        for key, batch in listing_page(self.path, BATCHES.items())]}, sort_keys=True).encode())

    @route('GET', '/batch/<batch_id>', query_parameters=LIST_QUERY_PARAMETERS)
    def batch(self, batch_id):
        """List chunk and result URLs for a batch ID returned by /batches."""
        if batch_id not in BATCHES:
            self.send_error(404)
            return
        batch = BATCHES[batch_id]
        names = listing_page(self.path, batch['chunks'])
        self.send_bytes(json.dumps(dict(batch, run_id=MANIFEST['run_id'],
            chunks=['/chunk/' + name for name in names],
            results=['/result/' + name for name in names]), sort_keys=True).encode())

    @route('GET', '/chunks', query_parameters=LIST_QUERY_PARAMETERS)
    def chunks(self):
        """List the run identity and all available source-chunk URLs."""
        self.send_bytes(json.dumps({'run_id': MANIFEST['run_id'],
            'chunks': ['/chunk/' + name for name in listing_page(self.path, NAMES)]}, sort_keys=True).encode())

    @route('GET', '/chunk/<name>', response_schema='/schema/input')
    def chunk(self, name):
        """Read a manifest-listed chunk; name includes the batch folder when present."""
        if name not in NAMES or not SAFE.fullmatch(name):
            self.send_error(404)
            return
        self.send_bytes(ARCHIVE.read('ai_analysis_input/' + name))

    @route('GET', '/result/<name>', response_schema='/schema/output')
    def result(self, name):
        """Read an accepted result using its full source_chunk path; 404 if absent."""
        if name not in NAMES or not SAFE.fullmatch(name):
            self.send_error(404)
            return
        try:
            with open(os.path.join(RESULTS, name), 'rb') as stream:
                self.send_bytes(stream.read())
        except FileNotFoundError:
            self.send_error(404)

    @route('GET', '/export', 'application/zip')
    def export(self):
        """Download a ZIP of the manifest, source chunks and validated stored results."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as dest:
            dest.writestr('ai_analysis_bundle_manifest.json',
                          ARCHIVE.read('ai_analysis_bundle_manifest.json'))
            for name in NAMES:
                source = ARCHIVE.read('ai_analysis_input/' + name)
                dest.writestr('ai_analysis_input/' + name, source)
                file = os.path.join(RESULTS, name)
                if os.path.isfile(file):
                    with open(file, 'rb') as stream:
                        data = stream.read()
                    validate(name, json.loads(data))
                    dest.writestr('results/' + name, data)
        self.send_bytes(buf.getvalue())

    @route('PUT', '/result/<name>', request_content_type='application/json',
           request_schema='/schema/output', min_body_bytes=1, max_body_bytes=MAX_RESULT_BYTES)
    def put_result(self, name):
        """Validate and atomically replace a result for a manifest-listed source_chunk path."""
        if name not in NAMES or not SAFE.fullmatch(name):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < self.active_route['min_body_bytes'] or length > self.active_route['max_body_bytes']:
                raise ValueError('Result must be 1..%s bytes' % self.active_route['max_body_bytes'])
            data = self.rfile.read(length)
            validate(name, json.loads(data))
            result_dir = os.path.dirname(os.path.join(RESULTS, name))
            os.makedirs(result_dir, exist_ok=True)
            fd, temp = tempfile.mkstemp(dir=result_dir, prefix='.upload-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                os.replace(temp, os.path.join(RESULTS, name))
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            self.send_bytes(b'{"status":"ok"}')
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.send_error(400, str(exc))

def connection_url(host, port):
    connect_host = '127.0.0.1' if host == '0.0.0.0' else host
    return 'http://%s:%s/' % (connect_host, port)


def build_parser():
    parser = argparse.ArgumentParser(description='Serve portable AI commit analysis work package')
    parser.add_argument('port', type=int, nargs='?', default=8000)
    parser.add_argument('host', nargs='?', default='127.0.0.1')
    parser.add_argument('-d', '--debug', '--no-daemon', dest='no_daemon',
                        action='store_true', help='Run in foreground without detaching')
    parser.add_argument('-l', '--log-file', metavar='PATH',
                        help='Log only to this file; required in daemon mode')
    parser.add_argument('--auth', metavar='USER:PASSWORD', help='Require HTTP Basic authentication')
    return parser


def auth_credentials(parser, value):
    if value is None:
        return None
    user, separator, password = value.partition(':')
    if not separator or not user or not password or any(ord(c) < 32 or ord(c) == 127 for c in value):
        parser.error('--auth requires a nonempty USER:PASSWORD without control characters')
    return value.encode('utf-8')


def stop_server(signum, frame):
    raise SystemExit(0)


def detach():
    # A readiness pipe prevents reporting success before detachment completes.
    read_fd, write_fd = os.pipe()
    try:
        pid = os.fork()
    except OSError:
        os.close(read_fd)
        os.close(write_fd)
        raise
    if pid:
        os.close(write_fd)
        with os.fdopen(read_fd, 'rb') as pipe:
            ready = pipe.read().decode('ascii').strip()
        os.waitpid(pid, 0)
        if not ready.isdigit():
            raise OSError('Daemon failed during startup')
        return int(ready)
    os.close(read_fd)
    try:
        os.setsid()
        if os.fork():
            os._exit(0)
        os.umask(0o077)
        with open(os.devnull, 'rb') as source:
            os.dup2(source.fileno(), 0)
        with open(os.devnull, 'ab') as target:
            os.dup2(target.fileno(), 1)
            os.dup2(target.fileno(), 2)
        os.write(write_fd, str(os.getpid()).encode('ascii'))
        os.close(write_fd)
        return None
    except BaseException:
        os._exit(1)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    credentials = auth_credentials(parser, args.auth)
    if not 0 <= args.port <= 65535:
        parser.error('port must be in 0..65535 (0 selects an available port)')
    if not args.no_daemon and not args.log_file:
        parser.error('Daemon mode requires -l/--log-file PATH; use -d for stderr logging')
    if args.log_file is not None and not args.log_file.strip():
        parser.error('-l/--log-file PATH must not be empty')
    if not args.no_daemon and not hasattr(os, 'fork'):
        parser.error('Background operation requires Unix; use --no-daemon')
    log_path = os.path.abspath(args.log_file) if args.log_file is not None else None
    logger = logging.getLogger('kcommit-ai-server')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    server = stream = None
    handlers = []
    try:
        if log_path is not None:
            try:
                fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                stream = os.fdopen(fd, 'a', encoding='utf-8', buffering=1)
            except OSError:
                parser.error('Cannot open log file; choose a writable location with --log-file')
        handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
        formatter = logging.Formatter('%(asctime)sZ %(message)s', '%Y-%m-%dT%H:%M:%S')
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        handlers.append(handler)
        for handler in handlers:
            logger.addHandler(handler)
        server = http.server.HTTPServer((args.host, args.port), Handler)
        server.access_logger = logger
        server.auth_credentials = credentials
        signal.signal(signal.SIGTERM, stop_server)
        signal.signal(signal.SIGINT, stop_server)
        host, port = server.server_address[:2]
        url = connection_url(host, port)
        if credentials is None:
            logger.warning('SERVER WARNING: authentication disabled; all endpoints allow unauthenticated access')
        if not args.no_daemon:
            daemon_pid = detach()
            if daemon_pid is not None:
                print('Background server PID=%s address=%s:%s log=%s url=%s' %
                      (daemon_pid, host, port, log_path, url), flush=True)
                return 0
        else:
            print('AI server started in foreground (debug mode) | PID=%s | bind=%s:%s | logs=%s | URL=%s' %
                  (os.getpid(), host, port, log_path or 'stderr', url), flush=True)
        logger.info('SERVER start pid=%s address=%s:%s auth=%s url=%s',
                    os.getpid(), host, port, 'enabled' if credentials else 'disabled', url)
        try:
            server.serve_forever(poll_interval=0.2)
        finally:
            logger.info('SERVER stop pid=%s', os.getpid())
    except OSError as exc:
        print('Server startup failed: %s' % exc, file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.server_close()
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()
        if stream is not None:
            stream.close()
        ARCHIVE.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
'''

def generate_ai_serve_script(outdir, output_path):
    """Embed immutable inputs, prompt, schemas and manifest into an executable zipapp."""
    with open(TOOL_MANIFEST_PATH, encoding='utf-8') as stream:
        tool_manifest = json.load(stream)
    version = tool_manifest.get('version') if isinstance(tool_manifest, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError('MANIFEST.json must define a nonempty string version')
    server_version = {'tool_version': version, 'version_source': 'MANIFEST.json',
                      'captured_at': 'zipapp_generation'}
    assets = ('ai_analysis_prompt.md', 'ai_analysis_input_schema.json',
              'ai_analysis_result_schema.json', 'ai_analysis_bundle_manifest.json',
              'ai_server_front_page.md')
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr('ai_server_version.json',
                         json.dumps(server_version, sort_keys=True).encode('utf-8'))
        archive.writestr('__main__.py', _MAIN_SOURCE)
        for name in assets:
            archive.write(os.path.join(outdir, name), name)
        root = os.path.join(outdir, 'ai_analysis_input')
        with open(os.path.join(outdir, 'ai_analysis_bundle_manifest.json'), encoding='utf-8') as stream:
            manifest = json.load(stream)
        for name in sorted(manifest['chunks']):
            if not NAME.fullmatch(name):
                raise ValueError('Invalid chunk path in AI manifest')
            archive.write(os.path.join(root, name), 'ai_analysis_input/' + name)
    archive_buffer.seek(0)
    with open(output_path, 'wb') as target:
        zipapp.create_archive(archive_buffer, target=target, interpreter='/usr/bin/env python3')
    os.chmod(output_path, os.stat(output_path).st_mode | 0o111)
    return output_path
