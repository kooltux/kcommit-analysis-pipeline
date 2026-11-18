"""Real directory-package zipapps expose exact contract bytes and trusted metadata."""
import io
import json
import subprocess
import sys
import zipfile

import pytest

from lib.ai_contract import digest, encode, result_properties
from lib.ai_package_server import generate_ai_package_server
from lib.ai_preparation import build_package
from lib.ai_prompt_body import BODY_SCHEMAS, build_prompt_body
from lib.manifest import VERSION
from test_ai_preparation import snapshots
from test_ai_server_runtime import basic, request, running
from ai_submission_helpers import role_body

PAGE = b'# Portable role workflow guide'




@pytest.fixture
def package(snapshots):
    return build_package([{'commit': 'a' * 40}, {'commit': 'b' * 40}], {}, snapshots,
                         VERSION, chunk_size=1, batch_size=2)


@pytest.fixture
def app(package, tmp_path):
    target = tmp_path / 'serve_ai.pyz'
    generate_ai_package_server(package, PAGE, target)
    return target


def test_exact_snapshots_and_isolated_startup(app, package, tmp_path):
    with zipfile.ZipFile(app) as archive:
        for name, expected in package['files'].items():
            assert archive.read(name) == expected
        assert archive.read('ai_server_front_page.md') == PAGE
    result = subprocess.run([sys.executable, '-I', '-S', str(app), '--help'], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr




@pytest.mark.parametrize('member', ['ai_contract/prompts/analyst.md', 'ai_analysis_input/batch_001/001.json',
                                   'ai_analysis_result_schema.json', '__main__.py'])
def test_invalid_snapshots_never_replace_output(package, tmp_path, member):
    package['files'][member] = b'tampered'
    output = tmp_path / 'existing.pyz'
    output.write_bytes(b'unchanged')
    with pytest.raises(ValueError):
        generate_ai_package_server(package, PAGE, output)
    assert output.read_bytes() == b'unchanged'
    assert not list(tmp_path.glob('.serve-ai-*'))




@pytest.fixture
def workflow(package):
    name = next(iter(package['manifest']['chunks']))
    chunk = json.loads(package['files']['ai_analysis_input/' + name])
    schema = json.loads(package['files']['ai_contract/schemas/result.json'])
    item = {}
    for key, spec in result_properties(schema).items():
        kind = spec['type']
        item[key] = (None if isinstance(kind, list) else False if kind == 'boolean'
                     else [] if kind == 'array' else spec.get('enum', ['evidence'])[0])
    item.update(rv_agreement='agree', ai_risks_if_not_backported=['none'])
    sha = chunk['commits'][0]['commit']
    final = {key: chunk[key] for key in ('schema_version', 'run_id', 'source_chunk',
             'input_schema_checksum', 'output_schema_checksum', 'total_commits')}
    final.update(input_checksum=digest(package['files']['ai_analysis_input/' + name]),
                 analyzed_commits=1, analysis_status='complete', results={sha: item})
    documents = {'result': final}
    for role in ('analyst', 'cve', 'reviewer'):
        fields = result_properties(json.loads(package['files']['ai_contract/schemas/' + role + '.json']))
        documents[role] = dict(run_id=chunk['run_id'], source_chunk=name, role=role,
                               results={sha: {key: item[key] for key in fields}})
    return name, documents


















