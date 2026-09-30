"""Generate a self-contained AI exchange zipapp with validated result uploads."""
import io
import os
import zipapp
import zipfile

_MAIN_SOURCE = '''\
import argparse
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
SAFE = re.compile(r'^[0-9]+\.json$')
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
    def log_message(self, fmt, *args):
        pass

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

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Serve portable AI commit analysis work package')
    parser.add_argument('port', type=int, nargs='?', default=8001)
    parser.add_argument('host', nargs='?', default='127.0.0.1')
    args = parser.parse_args()
    http.server.HTTPServer((args.host, args.port), Handler).serve_forever()
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
