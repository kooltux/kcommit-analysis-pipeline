"""Publish an in-memory directory-contract package as a standalone AI server."""
import io
import inspect
import json
import os
import re
import tempfile
import zipapp
import zipfile

from lib import ai_serve_script_gen as server
from lib import ai_workflow
from lib.ai_assets import PROMPT_ROLES, SCHEMA_ROLES
from lib.ai_contract import NAME, digest, encode, validate_chunk

_CONTRACT_ROUTES = '''\
CONTRACT = MANIFEST['contract_assets']
for asset_name, expected in CONTRACT.items():
    if checksum(ARCHIVE.read('ai_contract/' + asset_name)) != expected:
        raise ValueError('Packaged contract checksum mismatch: ' + asset_name)
WORKFLOW_SCHEMAS = {role: json.loads(ARCHIVE.read('ai_contract/schemas/' + role + '.json'))
                    for role in ROLES + ('result',)}


@route('GET', '/contract', group='contract', order=0)
def contract_index(self):
    """Discover immutable contract assets and trusted source metadata URLs."""
    assets = {}
    for name, expected in CONTRACT.items():
        group, filename = name.split('/')
        stem = filename.rsplit('.', 1)[0]
        url = ('/prompt/' if group == 'prompts' else '/schema/') + stem
        assets[name] = {'checksum': expected, 'url': url}
    self.send_bytes(json.dumps({'run_id': MANIFEST['run_id'], 'assets': assets,
        'input_schema_checksum': MANIFEST['input_schema_checksum'],
        'output_schema_checksum': MANIFEST['output_schema_checksum'],
        'chunks': {name: '/metadata/' + name for name in NAMES}}, sort_keys=True).encode())


@route('GET', '/prompt/<role>', 'text/markdown; charset=utf-8', group='contract', order=2)
def role_prompt(self, role):
    """Retrieve exact prompt bytes for a role listed by /contract."""
    name = 'prompts/' + role + '.md'
    if name not in CONTRACT:
        self.send_error(404)
        return
    self.send_bytes(ARCHIVE.read('ai_contract/' + name))


@route('GET', '/schema/<role>', group='contract', order=4)
def role_schema(self, role):
    """Retrieve a packaged role/result schema listed by /contract."""
    name = 'schemas/' + role + '.json'
    if name not in CONTRACT:
        self.send_error(404)
        return
    self.send_bytes(ARCHIVE.read('ai_contract/' + name))


@route('GET', '/metadata/<name>', group='sources', order=4)
def source_metadata(self, name):
    """Copy trusted envelope fields into role/results; do not calculate hashes with an LLM.

    Returns schema_version, run_id, source_chunk, the exact-byte input_checksum,
    input_schema_checksum, output_schema_checksum and total_commits. Add your
    results, analyzed_commits and analysis_status separately. There is no bare
    /metadata endpoint; /contract lists valid per-chunk metadata URLs.
    """
    if name not in NAMES or not SAFE.fullmatch(name):
        self.send_error(404)
        return
    source = ARCHIVE.read('ai_analysis_input/' + name)
    if checksum(source) != NAMES[name]:
        raise ValueError('Source chunk checksum mismatch')
    chunk = json.loads(source)
    self.send_bytes(json.dumps(dict(schema_version='1.0', run_id=MANIFEST['run_id'],
        source_chunk=name, input_checksum=NAMES[name],
        input_schema_checksum=MANIFEST['input_schema_checksum'],
        output_schema_checksum=MANIFEST['output_schema_checksum'],
        total_commits=chunk['total_commits']), sort_keys=True).encode())


@route('POST', '/validate/workflow/<name>', request_content_type='application/json', group='validation', order=1,
       description='Validate the analyst, cve, reviewer and result documents supplied together in the POST body, including coverage and exact value preservation. The URL selects the source chunk; nothing is stored.',
       min_body_bytes=1, max_body_bytes=MAX_RESULT_BYTES,
       document_roles=['analyst', 'cve', 'reviewer', 'result'], writes_results=False)
@route('POST', '/validate/role/<role>/<name>', request_content_type='application/json', group='validation', order=0,
       description='Validate one complete role document supplied in the POST body. The URL selects the role and source chunk; nothing is stored and other roles are not cross-checked.',
       request_schema='/schema/<role>', min_body_bytes=1, max_body_bytes=MAX_RESULT_BYTES,
       roles=['analyst', 'cve', 'reviewer'], writes_results=False)
def validate_contributions(self, name, role=None):
    """Validate role JSON or four workflow documents without storing results.

    Use archived source bytes, manifest identities and packaged schemas only.
    A role gate checks one document; the workflow gate also checks coverage and
    exact assembly preservation. Neither gate applies review recommendations.
    """
    if name not in NAMES or not SAFE.fullmatch(name) or (role is not None and role not in ROLES):
        self.send_error(404)
        return
    source = ARCHIVE.read('ai_analysis_input/' + name)
    if checksum(source) != NAMES[name]:
        raise ValueError('Source chunk checksum mismatch')
    chunk = json.loads(source)
    chunk.update(run_id=MANIFEST['run_id'], source_chunk=name,
                 input_schema_checksum=MANIFEST['input_schema_checksum'],
                 output_schema_checksum=MANIFEST['output_schema_checksum'],
                 total_commits=len(chunk['commits']))
    try:
        lengths = self.headers.get_all('Content-Length', [])
        if len(lengths) != 1 or self.headers.get('Transfer-Encoding') is not None:
            raise ValueError('One Content-Length and no Transfer-Encoding are required')
        raw_length = lengths[0].strip()
        if not re.fullmatch(r'[0-9]+', raw_length):
            raise ValueError('Invalid Content-Length')
        length = int(raw_length)
        if not self.active_route['min_body_bytes'] <= length <= self.active_route['max_body_bytes']:
            raise ValueError('Validation body must be 1..%s bytes' % self.active_route['max_body_bytes'])
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError('Truncated validation body')
        def unique(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('Duplicate JSON key: ' + key)
                value[key] = item
            return value
        def invalid_constant(value):
            raise ValueError('Invalid JSON constant: ' + value)
        document = json.loads(data.decode('utf-8'), object_pairs_hook=unique,
                              parse_constant=invalid_constant)
        if role is None:
            validate_workflow(document, chunk, WORKFLOW_SCHEMAS, checksum(source))
        else:
            validate_role(role, document, chunk, WORKFLOW_SCHEMAS, checksum(source))
        self.send_bytes(json.dumps(dict(status='valid', run_id=MANIFEST['run_id'],
                                        source_chunk=name), sort_keys=True).encode())
    except (ValueError, UnicodeError, RecursionError) as exc:
        self.close_connection = True
        self.send_error(400, str(exc))
'''


def _checked_files(package):
    if (not isinstance(package, dict) or set(package) != {'manifest', 'files'}
            or not isinstance(package['manifest'], dict) or not isinstance(package['files'], dict)):
        raise ValueError('Invalid prepared package structure')
    manifest, files = package['manifest'], dict(package['files'])
    required_fields = {'contract_assets', 'chunks', 'run_id', 'input_schema_checksum',
                       'output_schema_checksum', 'prompt_checksum', 'total_commits', 'total_chunks'}
    if required_fields - set(manifest):
        raise ValueError('Incomplete prepared package manifest')
    if files.get('ai_analysis_bundle_manifest.json') != encode(manifest):
        raise ValueError('Prepared manifest bytes do not match metadata')
    hashes, chunks = manifest['contract_assets'], manifest['chunks']
    required = ({'prompts/' + role + '.md' for role in PROMPT_ROLES}
                | {'schemas/' + role + '.json' for role in SCHEMA_ROLES})
    if not isinstance(hashes, dict) or required - set(hashes):
        raise ValueError('Prepared package lacks required contract assets')
    if not isinstance(chunks, dict) or not chunks:
        raise ValueError('Prepared package requires source chunks')
    for name, expected in hashes.items():
        if not isinstance(name, str) or not re.fullmatch(
                r'(?:prompts/[A-Za-z0-9][A-Za-z0-9_-]*[.]md|schemas/[A-Za-z0-9][A-Za-z0-9_-]*[.]json)', name):
            raise ValueError('Invalid contract asset path')
        data = files.get('ai_contract/' + name)
        if not isinstance(data, bytes) or digest(data) != expected:
            raise ValueError('Contract asset checksum mismatch: ' + name)
    for filename, key in [('ai_analysis_prompt.md', 'prompt_checksum'),
                          ('ai_analysis_input_schema.json', 'input_schema_checksum'),
                          ('ai_analysis_result_schema.json', 'output_schema_checksum')]:
        data = files.get(filename)
        if not isinstance(data, bytes) or digest(data) != manifest[key]:
            raise ValueError('Root asset checksum mismatch: ' + filename)
    if (files['ai_analysis_input_schema.json'] != files['ai_contract/schemas/input.json']
            or files['ai_analysis_result_schema.json'] != files['ai_contract/schemas/result.json']):
        raise ValueError('Root schema differs from selected contract')
    seen = set()
    for name, expected in chunks.items():
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError('Invalid source chunk path')
        data = files.get('ai_analysis_input/' + name)
        if not isinstance(data, bytes) or digest(data) != expected:
            raise ValueError('Source chunk checksum mismatch: ' + name)
        chunk = json.loads(data)
        validate_chunk(chunk, manifest['input_schema_checksum'], manifest['output_schema_checksum'],
                       manifest['run_id'], name)
        shas = {item['commit'] for item in chunk['commits']}
        if seen & shas:
            raise ValueError('Duplicate source SHA across chunks')
        seen.update(shas)
    if len(seen) != manifest['total_commits'] or len(chunks) != manifest['total_chunks']:
        raise ValueError('Prepared package total mismatch')
    allowed = ({'ai_analysis_bundle_manifest.json', 'ai_analysis_prompt.md',
                'ai_analysis_input_schema.json', 'ai_analysis_result_schema.json'}
               | {'ai_contract/' + name for name in hashes}
               | {'ai_analysis_input/' + name for name in chunks})
    if set(files) != allowed or any(not isinstance(data, bytes) for data in files.values()):
        raise ValueError('Unexpected prepared package file or type')
    return files


def generate_ai_package_server(package, front_page_bytes, output_path):
    """Validate snapshots before atomically publishing a self-contained zipapp.

    Stage 08 uses this directory-contract entry point; there is no fallback to
    file-based contract selection.
    """
    if not isinstance(front_page_bytes, bytes) or not front_page_bytes.decode('utf-8').strip():
        raise ValueError('Front page must be nonempty UTF-8 Markdown bytes')
    files = _checked_files(package)
    marker = "\nif __name__ == '__main__':\n"
    if server._MAIN_SOURCE.count(marker) != 1:
        raise ValueError('Portable server entry point is not unique')
    workflow_source = 'ROLES = ' + repr(ai_workflow.ROLES) + '\n\n'
    workflow_source += '\n\n'.join(inspect.getsource(fn) for fn in
                                    (ai_workflow.validate_role, ai_workflow.validate_workflow))
    source = server._MAIN_SOURCE.replace(
        marker, '\n' + workflow_source + '\n' + _CONTRACT_ROUTES + '\n' + marker, 1)
    compile(source, '__main__.py', 'exec')
    with open(server.TOOL_MANIFEST_PATH, encoding='utf-8') as stream:
        tool_manifest = json.load(stream)
    version = tool_manifest.get('version') if isinstance(tool_manifest, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError('MANIFEST.json must define a nonempty string version')
    metadata = dict(tool_version=version, version_source='MANIFEST.json', captured_at='zipapp_generation')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr('__main__.py', source)
        archive.writestr('ai_server_version.json', encode(metadata))
        archive.writestr('ai_server_front_page.md', front_page_bytes)
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    buffer.seek(0)
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(output_path)), prefix='.serve-ai-')
    try:
        with os.fdopen(fd, 'wb') as target:
            zipapp.create_archive(buffer, target=target, interpreter='/usr/bin/env python3')
        os.chmod(temporary, 0o755)
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output_path
