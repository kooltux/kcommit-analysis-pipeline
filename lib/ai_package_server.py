"""Publish an in-memory directory-contract package as a standalone AI server."""
import io
import json
import os
import re
import tempfile
import zipapp
import zipfile

from lib import ai_serve_script_gen as server
from lib.ai_assets import PROMPT_ROLES, SCHEMA_ROLES
from lib.ai_contract import NAME, digest, encode, validate_chunk
from lib.ai_code_assets import read_embedded_source



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
    base_source = server.build_main_source()
    if base_source.count(marker) != 1:
        raise ValueError('Portable server entry point is not unique')
    workflow_source = read_embedded_source('workflow')
    contract_routes = read_embedded_source('contract_routes')
    helpers = {name: read_embedded_source(name) for name in ('validation', 'prompt_body')}
    source = base_source
    entrypoint = read_embedded_source('entrypoint')
    package_init = read_embedded_source('package')
    runtime_name = 'kcap_ai_runtime/server.py'
    compile(source, runtime_name, 'exec')
    with open(server.TOOL_MANIFEST_PATH, encoding='utf-8') as stream:
        tool_manifest = json.load(stream)
    version = tool_manifest.get('version') if isinstance(tool_manifest, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError('MANIFEST.json must define a nonempty string version')
    metadata = dict(tool_version=version, version_source='MANIFEST.json', captured_at='zipapp_generation')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr('__main__.py', entrypoint)
        archive.writestr('kcap_ai_runtime/__init__.py', package_init)
        archive.writestr(runtime_name, source)
        archive.writestr('kcap_ai_runtime/workflow.py', workflow_source)
        archive.writestr('kcap_ai_runtime/contract_routes.py', contract_routes)
        for name, data in helpers.items():
            archive.writestr('kcap_ai_runtime/' + name + '.py', data)
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
