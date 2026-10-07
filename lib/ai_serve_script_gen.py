"""Generate a self-contained AI exchange zipapp with validated result uploads."""
import io
import os
import zipapp
import zipfile

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
SCHEMA = json.loads(ARCHIVE.read('ai_analysis_result_schema.json'))
NAMES = MANIFEST['chunks']
SAFE = re.compile(r'^[0-9]+[.]json$')
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

class Handler(http.server.BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(10)
        super().setup()

    def log_message(self, fmt, *args):
        # Suppress default messages, including duplicate error logging.
        pass

    def log_request(self, code='-', size='-'):
        path = getattr(self, 'path', '').split('?', 1)[0]
        if path.startswith(('http://', 'https://')):
            try:
                path = urllib.parse.urlsplit(path).path
            except ValueError:
                path = '<invalid-target>'
        method = getattr(self, 'command', None) or '-'
        self.server.access_logger.info('%s %s %s %s',
            self.client_address[0], json.dumps(method, ensure_ascii=True),
            json.dumps(path, ensure_ascii=True), code)

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

    def send_bytes(self, data, kind='application/json'):
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        files = {'/prompt': ('ai_analysis_prompt.md', 'text/markdown'),
                 '/schema/input': ('ai_analysis_input_schema.json', 'application/json'),
                 '/schema/output': ('ai_analysis_result_schema.json', 'application/json')}
        if path in files:
            member, kind = files[path]
            self.send_bytes(ARCHIVE.read(member), kind)
            return
        if path == '/chunks':
            self.send_bytes(json.dumps({'run_id': MANIFEST['run_id'],
                                        'chunks': ['/chunk/' + n for n in NAMES]},
                                       sort_keys=True).encode())
            return
        if path.startswith('/chunk/'):
            name = path[len('/chunk/'): ]
            if name in NAMES and SAFE.fullmatch(name):
                self.send_bytes(ARCHIVE.read('ai_analysis_input/' + name))
                return
        if path.startswith('/result/'):
            name = path[len('/result/'): ]
            if name in NAMES and SAFE.fullmatch(name):
                try:
                    with open(os.path.join(RESULTS, name), 'rb') as stream:
                        self.send_bytes(stream.read())
                    return
                except FileNotFoundError:
                    pass
        if path == '/export':
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
            self.send_bytes(buf.getvalue(), 'application/zip')
            return
        self.send_error(404)

    def do_PUT(self):
        path = self.path.split('?', 1)[0]
        name = path[len('/result/'):] if path.startswith('/result/') else ''
        if name not in NAMES or not SAFE.fullmatch(name):
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 10 * 1024 * 1024:
                raise ValueError('Result must be 1..10485760 bytes')
            data = self.rfile.read(length)
            validate(name, json.loads(data))
            os.makedirs(RESULTS, exist_ok=True)
            fd, temp = tempfile.mkstemp(dir=RESULTS, prefix='.upload-')
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

def build_parser():
    parser = argparse.ArgumentParser(description='Serve portable AI commit analysis work package')
    parser.add_argument('port', type=int, nargs='?', default=8000)
    parser.add_argument('host', nargs='?', default='0.0.0.0')
    parser.add_argument('-d', '--debug', '--no-daemon', dest='no_daemon',
                        action='store_true', help='Run in foreground without detaching')
    parser.add_argument('--log-file', default='/var/log/kcommit-analyze-ai-server.log')
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
    if not args.no_daemon and not hasattr(os, 'fork'):
        parser.error('Background operation requires Unix; use --no-daemon')
    log_path = os.path.abspath(args.log_file)
    logger = logging.getLogger('kcommit-ai-server')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    server = stream = None
    handlers = []
    try:
        try:
            fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            stream = os.fdopen(fd, 'a', encoding='utf-8', buffering=1)
        except OSError:
            parser.error('Cannot open log file; choose a writable location with --log-file')
        handler = logging.StreamHandler(stream)
        formatter = logging.Formatter('%(asctime)sZ %(message)s', '%Y-%m-%dT%H:%M:%S')
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        handlers.append(handler)
        if args.no_daemon:
            console = logging.StreamHandler(sys.stderr)
            console.setFormatter(formatter)
            handlers.append(console)
        for handler in handlers:
            logger.addHandler(handler)
        server = http.server.HTTPServer((args.host, args.port), Handler)
        server.access_logger = logger
        server.auth_credentials = credentials
        signal.signal(signal.SIGTERM, stop_server)
        signal.signal(signal.SIGINT, stop_server)
        host, port = server.server_address[:2]
        if credentials is None:
            print('WARNING: authentication disabled; all endpoints allow unauthenticated access',
                  file=sys.stderr, flush=True)
        if not args.no_daemon:
            daemon_pid = detach()
            if daemon_pid is not None:
                print('Background server PID=%s address=%s:%s log=%s' %
                      (daemon_pid, host, port, log_path), flush=True)
                return 0
        logger.info('SERVER start pid=%s address=%s:%s auth=%s',
                    os.getpid(), host, port, 'enabled' if credentials else 'disabled')
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
    assets = ('ai_analysis_prompt.md', 'ai_analysis_input_schema.json',
              'ai_analysis_result_schema.json', 'ai_analysis_bundle_manifest.json')
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr('__main__.py', _MAIN_SOURCE)
        for name in assets:
            archive.write(os.path.join(outdir, name), name)
        root = os.path.join(outdir, 'ai_analysis_input')
        for name in sorted(os.listdir(root)):
            if name.endswith('.json'):
                archive.write(os.path.join(root, name), 'ai_analysis_input/' + name)
    archive_buffer.seek(0)
    with open(output_path, 'wb') as target:
        zipapp.create_archive(archive_buffer, target=target, interpreter='/usr/bin/env python3')
    os.chmod(output_path, os.stat(output_path).st_mode | 0o111)
    return output_path
