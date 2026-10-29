"""Generate a self-contained AI exchange zipapp with validated result uploads."""
import inspect
from lib.ai_contract import result_properties, validate_result
import os

_RESULT_VALIDATION_SOURCE = '\n\n'.join(inspect.getsource(fn) for fn in (result_properties, validate_result))

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
CONTRACT = MANIFEST['contract_assets']
SCHEMA = json.loads(ARCHIVE.read('ai_contract/schemas/result.json'))
NAMES = MANIFEST['chunks']
SAFE = re.compile(r'^(?:batch_[0-9]{3,}/)?[0-9]+[.]json$')
BATCHES = {batch['batch_id']: batch for batch in MANIFEST.get('batches', [])}
RESULTS = os.path.abspath(sys.argv[0]) + '.results'

def checksum(data):
    return hashlib.sha256(data).hexdigest()


for asset_name, expected in CONTRACT.items():
    if checksum(ARCHIVE.read('ai_contract/' + asset_name)) != expected:
        raise ValueError('Packaged contract checksum mismatch: ' + asset_name)


def decode_json(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON key: ' + key)
            value[key] = item
        return value
    def invalid_constant(value):
        raise ValueError('Invalid JSON constant: ' + value)
    return json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid_constant)

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
    bound_chunk = dict(chunk, run_id=MANIFEST['run_id'], source_chunk=name,
                       input_schema_checksum=MANIFEST['input_schema_checksum'],
                       output_schema_checksum=MANIFEST['output_schema_checksum'],
                       total_commits=len(chunk['commits']))
    return validate_result(value, bound_chunk, SCHEMA, checksum(source))

ROUTES = []
MAX_RESULT_BYTES = 10 * 1024 * 1024
LIST_QUERY_PARAMETERS = {
    'limit': {'type': 'integer', 'default': 0, 'minimum': 0, 'example': 1,
              'description': 'Maximum returned items; absent or zero means unlimited. A supplied value must be a nonnegative integer and occur once.'},
    'offset': {'type': 'integer', 'default': 0, 'minimum': 0, 'example': 0,
               'description': 'Zero-based number of items to skip; absent means zero. A supplied value must be a nonnegative integer and occur once.'},
}


def listing_page(target, values):
    """Apply offset before limit without changing order or the source collection."""
    query = urllib.parse.parse_qs(target.partition('?')[2], keep_blank_values=True)
    unknown = set(query) - set(LIST_QUERY_PARAMETERS)
    if unknown:
        raise ValueError('Unknown pagination parameter: ' + ', '.join(sorted(unknown)))
    numbers = {}
    for name, spec in LIST_QUERY_PARAMETERS.items():
        values_for_name = query.get(name, [str(spec['default'])])
        if len(values_for_name) != 1:
            raise ValueError('Repeated pagination parameter: ' + name)
        raw = values_for_name[0].strip()
        if not re.fullmatch(r'[+-]?[0-9]+', raw):
            raise ValueError('Pagination parameter must be an integer: ' + name)
        number = int(raw)
        if number < spec['minimum']:
            raise ValueError('Pagination parameter must be nonnegative: ' + name)
        numbers[name] = number
    offset, limit = numbers['offset'], numbers['limit']
    items = list(values)
    return items[offset:offset + limit if limit else None]




def route(method, path, content_type='application/json', **contract):
    """Register an executable route and its machine-readable contract together."""
    parameters = re.findall(r'<([a-z_]+)>', path)
    pattern = re.escape(path)
    for name in parameters:
        capture = '.+' if name == parameters[-1] else '[^/]+'
        pattern = pattern.replace('<' + name + '>', '(?P<' + name + '>' + capture + ')')
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
        reasons = {400: 'invalid_result' if method == 'POST' else 'malformed_request',
                   405: 'method_not_allowed',
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
            self.send_error(401)
        return valid

    def send_error(self, code, message=None, explain=None):
        self.close_connection = True
        names = {400: 'invalid_request', 401: 'authentication_failed', 404: 'not_found',
                 405: 'method_not_allowed', 408: 'timeout', 414: 'request_line_too_long',
                 431: 'headers_too_large', 500: 'internal_error', 501: 'unsupported_method'}
        message = self.responses.get(code, ('Request failed',))[0] if message is None or code >= 500 else str(message)
        data = json.dumps({'error': {'code': names.get(code, 'http_error'),
                                   'status': code, 'message': message}}, sort_keys=True).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Connection', 'close')
        if code == 401:
            self.send_header('WWW-Authenticate', 'Basic realm="kcommit-analyze-ai", charset="UTF-8"')
        if code == 405:
            self.send_header('Allow', ', '.join(self.allowed_methods))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(data)

    def read_json(self):
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or self.headers.get('Transfer-Encoding') is not None:
            raise ValueError('One Content-Length and no Transfer-Encoding are required')
        raw = lengths[0].strip()
        if not re.fullmatch(r'[0-9]+', raw):
            raise ValueError('Invalid Content-Length')
        length = int(raw)
        if not self.active_route['min_body_bytes'] <= length <= self.active_route['max_body_bytes']:
            raise ValueError('Body exceeds the declared size limits')
        types = self.headers.get_all('Content-Type', [])
        if len(types) != 1 or types[0].split(';', 1)[0].strip().lower() != 'application/json':
            raise ValueError('One application/json Content-Type is required')
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError('Truncated JSON body')
        return data, decode_json(data)

    def send_bytes(self, data, kind=None):
        kind = kind or getattr(self, 'active_route', {}).get('response_content_type', 'application/json')
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.dispatch('GET')

    def do_POST(self):
        self.dispatch('POST')

    def do_PUT(self):
        self.dispatch('PUT')

    def dispatch(self, method):
        path = self.path.split('?', 1)[0]
        for item in ROUTES:
            match = item['matcher'].fullmatch(path)
            if item['method'] == method and match:
                self.active_route = item
                try:
                    if item.get('query_parameters') == LIST_QUERY_PARAMETERS:
                        listing_page(self.path, ())
                except ValueError as exc:
                    self.send_error(400, str(exc))
                    return
                item['handler'](self, **match.groupdict())
                return
        self.allowed_methods = sorted({item['method'] for item in ROUTES if item['matcher'].fullmatch(path)})
        self.send_error(405 if self.allowed_methods else 404)

    @route('GET', '/api', group='discovery', order=0)
    def api(self):
        """Describe routes from the executable registry, not a packaged document."""
        groups = ['discovery', 'contract', 'sources', 'validation', 'results', 'other']
        assets = globals().get('CONTRACT', {})
        routes = []
        for item in ROUTES:
            if not callable(getattr(type(self), 'do_' + item['method'], None)):
                continue
            entry = {key: value for key, value in item.items() if key not in ('handler', 'matcher')}
            entry.setdefault('group', 'other')
            entry.setdefault('order', 0)
            entry['description'] = entry.get('description') or (item['handler'].__doc__ or '').strip()
            if entry.get('request_content_type'):
                body = dict(required=True, content_type=entry['request_content_type'])
                if entry.get('document_roles'):
                    documents = entry['document_roles']
                    body['schema'] = dict(type='object', required=list(documents), additionalProperties=False,
                        properties={role: {'$ref': '/schema/' + role} for role in documents})
                    body['description'] = 'An object containing complete JSON documents, not filenames or chunk names; the assembled document is nested under result.'
                elif entry.get('request_schema'):
                    body['schema'] = {'$ref': entry['request_schema']}
                    body['description'] = 'A complete JSON document conforming to the referenced schema, not the source chunk or its name. Replace <role> in the schema reference with the URL role when present.'
                entry['request_body'] = body
            choices = {'chunks': sorted(NAMES), 'batches': sorted(BATCHES), 'roles': list(entry.get('roles', []))}
            for group in ('prompts', 'schemas'):
                choices[group] = sorted(name.split('/')[1].rsplit('.', 1)[0] for name in assets if name.startswith(group + '/'))
            descriptions = {'chunks': 'Source chunk path from /chunks, including its batch folder.',
                            'batches': 'Batch identifier from /batches.', 'roles': 'Intermediate validation role.',
                            'prompts': 'Selected prompt name from /contract.', 'schemas': 'Selected schema name from /contract.'}
            sources = entry.pop('parameter_sources', {})
            entry['path_parameters'] = {}
            url = entry['path']
            for parameter in entry['parameters']:
                source = sources.get(parameter)
                values = choices.get(source, [])
                value = ('analyst' if source in ('roles', 'prompts') and 'analyst' in values else next(iter(values), None))
                spec = dict(type='string', description=descriptions.get(source, 'Route path parameter.'), example=value)
                if source in ('roles', 'prompts', 'schemas'):
                    spec['enum'] = list(values)
                entry['path_parameters'][parameter] = spec
                if value is not None:
                    url = url.replace('<' + parameter + '>', urllib.parse.quote(value, safe='/'))
            entry['examples'] = []
            if '<' not in url:
                entry['examples'].append(dict(method=entry['method'], url=url))
                if entry.get('query_parameters'):
                    query = {key: spec.get('example', spec.get('default', 0)) for key, spec in entry['query_parameters'].items()}
                    query_url = url + '?' + urllib.parse.urlencode(query)
                    entry['examples'].append(dict(method=entry['method'], url=query_url))
            routes.append(entry)
        routes.sort(key=lambda entry: (groups.index(entry['group']) if entry['group'] in groups else len(groups),
                    entry['order'], entry['path'], {'GET': 0, 'POST': 1}.get(entry['method'], 9)))
        required = self.server.auth_credentials is not None
        self.send_bytes(json.dumps({'run_id': MANIFEST['run_id'], 'groups': groups, 'routes': routes,
            'authentication': {'required': required, 'scheme': 'Basic' if required else None}},
            sort_keys=True).encode())

    @route('GET', '/api/version', group='discovery', order=1)
    def version(self):
        """Report the tool manifest version captured when this zipapp was generated."""
        self.send_bytes(json.dumps(SERVER_VERSION, sort_keys=True).encode())

    @route('GET', '/', 'text/markdown; charset=utf-8', group='discovery', order=2)
    def front_page(self):
        """Read the shared human, AI-client and automation guide."""
        self.send_bytes(ARCHIVE.read('ai_server_front_page.md'))

    @route('GET', '/prompt/<name>', 'text/markdown; charset=utf-8', group='contract', order=1,
           parameter_sources={'name': 'prompts'})
    def prompt_asset(self, name):
        """Retrieve one selected prompt; execute roles separately, never a combined catalog."""
        asset = 'prompts/' + name + '.md'
        if asset not in CONTRACT:
            self.send_error(404)
            return
        self.send_bytes(ARCHIVE.read('ai_contract/' + asset))

    @route('GET', '/schema/<name>', group='contract', order=2,
           parameter_sources={'name': 'schemas'})
    def schema_asset(self, name):
        """Retrieve one selected schema: input, a specialist/reviewer, result, or an additional asset."""
        asset = 'schemas/' + name + '.json'
        if asset not in CONTRACT:
            self.send_error(404)
            return
        self.send_bytes(ARCHIVE.read('ai_contract/' + asset))

    @route('GET', '/batches', query_parameters=LIST_QUERY_PARAMETERS, group='sources', order=0)
    def batches(self):
        """List batch assignments, member chunk paths and discovery URLs."""
        self.send_bytes(json.dumps({'run_id': MANIFEST['run_id'],
            'batch_size': MANIFEST.get('batch_size'), 'total_batches': len(BATCHES),
            'batches': [dict(batch, url='/batch/' + key)
                        for key, batch in listing_page(self.path, BATCHES.items())]}, sort_keys=True).encode())

    @route('GET', '/batch/<batch_id>', query_parameters=LIST_QUERY_PARAMETERS, group='sources', order=1, parameter_sources={'batch_id': 'batches'})
    def batch(self, batch_id):
        """List paired chunk/result URLs in chunks for a batch ID returned by /batches."""
        if batch_id not in BATCHES:
            self.send_error(404)
            return
        batch = BATCHES[batch_id]
        names = listing_page(self.path, batch['chunks'])
        self.send_bytes(json.dumps(dict(batch, run_id=MANIFEST['run_id'],
            chunks=[{'chunk': '/chunk/' + name, 'result': '/result/' + name}
                    for name in names]), sort_keys=True).encode())

    @route('GET', '/chunks', query_parameters=LIST_QUERY_PARAMETERS, group='sources', order=2)
    def chunks(self):
        """List the run identity and all available source-chunk URLs."""
        self.send_bytes(json.dumps({'run_id': MANIFEST['run_id'],
            'chunks': ['/chunk/' + name for name in listing_page(self.path, NAMES)]}, sort_keys=True).encode())

    @route('GET', '/chunk/<name>', response_schema='/schema/input', group='sources', order=3, parameter_sources={'name': 'chunks'})
    def chunk(self, name):
        """Read a manifest-listed chunk; name includes the batch folder when present."""
        if name not in NAMES or not SAFE.fullmatch(name):
            self.send_error(404)
            return
        self.send_bytes(ARCHIVE.read('ai_analysis_input/' + name))

    @route('GET', '/result/<name>', response_schema='/schema/result', group='results', order=0, parameter_sources={'name': 'chunks'})
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

    @route('GET', '/export', 'application/zip', group='results', order=1)
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

    @route('POST', '/result/<name>', request_content_type='application/json', group='results', order=0, parameter_sources={'name': 'chunks'},
           request_schema='/schema/result', min_body_bytes=1, max_body_bytes=MAX_RESULT_BYTES)
    def post_result(self, name):
        """Validate and atomically replace a result for a manifest-listed source_chunk path."""
        if name not in NAMES or not SAFE.fullmatch(name):
            self.send_error(404)
            return
        try:
            data, document = self.read_json()
            validate(name, document)
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
        except (ValueError, UnicodeError, RecursionError) as exc:
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

_MAIN_SOURCE = _RESULT_VALIDATION_SOURCE + '\n' + _MAIN_SOURCE

