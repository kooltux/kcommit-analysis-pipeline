"""Shared validation snapshots work directly and in dependency-free zipapps."""
import ast
import copy
import inspect
import io
import json
import subprocess
import sys
import zipfile

import pytest

from lib.ai_contract import digest, encode, input_schema, result_properties, validate_result
from lib.ai_serve_script_gen import _MAIN_SOURCE, generate_ai_serve_script
from test_ai_review_runtime import payload, SHA, NOTE, RECOMMENDATION
from test_ai_server_runtime import request, running


@pytest.fixture
def contract_app(payload, tmp_path):
    schema, chunk, result = copy.deepcopy(payload)
    schema_bytes = encode(schema)
    input_bytes = encode(input_schema())
    for target in (chunk, result):
        target['input_schema_checksum'] = digest(input_bytes)
        target['output_schema_checksum'] = digest(schema_bytes)
    source = encode(chunk)
    result['input_checksum'] = digest(source)
    name = chunk['source_chunk']
    source_path = tmp_path / 'ai_analysis_input' / name
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source)
    manifest = dict(run_id=chunk['run_id'], chunks={name: digest(source)},
                    input_schema_checksum=digest(input_bytes),
                    output_schema_checksum=digest(schema_bytes), prompt_checksum=digest(b'prompt'))
    for filename, data in [
        ('ai_analysis_bundle_manifest.json', encode(manifest)),
        ('ai_analysis_input_schema.json', input_bytes),
        ('ai_analysis_result_schema.json', schema_bytes),
        ('ai_analysis_prompt.md', b'prompt'),
        ('ai_server_front_page.md', b'# Test guide'),
    ]:
        (tmp_path / filename).write_bytes(data)
    app = tmp_path / 'serve_ai.pyz'
    generate_ai_serve_script(str(tmp_path), str(app))
    return app, result


def test_embedded_functions_match_shared_source(contract_app):
    with zipfile.ZipFile(contract_app[0]) as archive:
        tree = ast.parse(archive.read('__main__.py'))
    definitions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for function in (result_properties, validate_result):
        expected = ast.parse(inspect.getsource(function)).body[0]
        assert ast.dump(definitions[function.__name__]) == ast.dump(expected)
    for node in ast.walk(tree):
        modules = ([node.module or ''] if isinstance(node, ast.ImportFrom) else
                   [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
        assert not any(name == 'lib' or name.startswith('lib.') or
                       name == 'jsonschema' or name.startswith('jsonschema.') for name in modules)


def test_isolated_zipapp_needs_no_repository_or_site_packages(contract_app, tmp_path):
    result = subprocess.run([sys.executable, '-I', '-S', str(contract_app[0]), '--help'],
                            cwd=tmp_path, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'Serve portable AI' in result.stdout


def test_direct_source_execution_uses_shared_validation(contract_app, monkeypatch):
    app, result = contract_app
    monkeypatch.setattr(sys, 'argv', [str(app)])
    namespace = {'__name__': 'server_contract_test'}
    exec(compile(_MAIN_SOURCE, '__main__.py', 'exec'), namespace)
    try:
        assert namespace['validate'](result['source_chunk'], result)
        bad = copy.deepcopy(result)
        bad['results'][SHA]['ai_is_security_fix'] = 1
        with pytest.raises(ValueError):
            namespace['validate'](result['source_chunk'], bad)
    finally:
        namespace['ARCHIVE'].close()


@pytest.mark.parametrize('method', ['PUT', 'POST'])
def test_live_upload_validation_preserves_accepted_result(contract_app, method):
    app, result = contract_app
    name = result['source_chunk']
    record = result['results'][SHA]
    candidates = [copy.deepcopy(result)]
    record.update(rv_agreement='disagree', rv_notes=[NOTE],
                  rv_recommendation=[RECOMMENDATION])
    candidates.append(copy.deepcopy(result))
    with running(app) as (port, log, errors):
        for candidate in candidates:
            data = encode(candidate)
            assert request(port, '/result/' + name, method=method, body=data)[0] == 200
            bad = copy.deepcopy(candidate)
            bad['results'][SHA]['rv_notes'] = []
            assert request(port, '/result/' + name, method=method, body=encode(bad))[0] == 400
            assert request(port, '/result/' + name)[2] == data
        status, _, exported = request(port, '/export')
        assert status == 200
        with zipfile.ZipFile(io.BytesIO(exported)) as archive:
            assert archive.read('results/' + name) == data
