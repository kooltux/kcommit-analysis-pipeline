"""Role prompts are served as complete static bodies with the schemas the role reads."""
import inspect
import json
from pathlib import Path
import re

import pytest

from lib.ai_assets import load_contract
from lib.ai_contract import digest
from lib.ai_package_server import generate_ai_package_server
from lib.ai_preparation import build_package
from lib.ai_prompt_body import BODY_SCHEMAS, build_prompt_body
from lib.manifest import VERSION
from test_ai_server_runtime import request, running

SAMPLES = Path(__file__).resolve().parents[1] / 'configs' / 'ai'
EXPECTED = {'analyst': ['input', 'analyst'], 'cve': ['input', 'cve'],
            'reviewer': ['input', 'analyst', 'cve', 'reviewer']}


@pytest.fixture
def files():
    return load_contract({'ai': {'prompts_dir': str(SAMPLES / 'prompts'),
                                 'schemas_dir': str(SAMPLES / 'schemas')}})['files']


def reader(files):
    return lambda path: files[path]


@pytest.mark.parametrize('role', sorted(EXPECTED))
def test_body_is_the_prompt_followed_by_the_schemas_the_role_reads(files, role):
    body = build_prompt_body(role, reader(files)).decode('utf-8')
    prompt = files['prompts/%s.md' % role].decode('utf-8').rstrip('\n')
    assert body.startswith(prompt + '\n\n## Artefacts\n')
    tail = body[len(prompt):]
    assert re.findall(r'^### .+ \((\w+)[.]json\)$', tail, re.M) == EXPECTED[role]
    assert '### Output schema (%s.json)' % role in tail
    for name in EXPECTED[role]:
        assert files['schemas/%s.json' % name].decode('utf-8').rstrip('\n') in tail
    assert tail.count('```json\n') == tail.count('\n```\n') == len(EXPECTED[role])


def test_body_is_deterministic_and_newline_terminated(files):
    first = build_prompt_body('reviewer', reader(files))
    assert first == build_prompt_body('reviewer', reader(dict(files)))
    assert first.endswith(b'\n```\n')


def test_body_mapping_and_standard_library_only_source():
    assert {role: [name for name, _ in pairs] for role, pairs in BODY_SCHEMAS.items()} == EXPECTED
    assert 'import ' not in inspect.getsource(build_prompt_body)


@pytest.fixture
def app(files, tmp_path):
    extended = dict(files)
    extended['prompts/notes.md'] = b'# Extra notes\n'
    package = build_package([{'commit': 'a' * 40}], {}, extended, VERSION)
    target = tmp_path / 'serve_ai.pyz'
    generate_ai_package_server(package, b'# Guide\n', target)
    return target


def test_server_serves_bodies_and_reports_them_in_the_contract(app, files):
    with running(app) as (port, log, errors):
        index = json.loads(request(port, '/contract')[2])
        for role in EXPECTED:
            status, headers, data = request(port, '/prompt/' + role)
            assert status == 200
            assert data == build_prompt_body(role, reader(files))
            entry = index['assets']['prompts/%s.md' % role]
            assert entry['checksum'] == digest(files['prompts/%s.md' % role])
            assert entry['body'] == {'bytes': len(data), 'checksum': digest(data)}


def test_other_prompt_assets_are_served_as_stored(app):
    with running(app) as (port, log, errors):
        status, headers, data = request(port, '/prompt/notes')
        assert (status, data) == (200, b'# Extra notes\n')
        entry = json.loads(request(port, '/contract')[2])['assets']['prompts/notes.md']
        assert 'body' not in entry
