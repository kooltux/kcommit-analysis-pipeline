"""Live documents are complete, version-local, checksum-exact and schema-consistent."""
import copy
import json
import re
import pytest
from jsonschema import Draft202012Validator
from lib.ai_contract import digest
from lib.ai_package_server import generate_ai_package_server
from lib.ai_preparation import build_package
from lib.manifest import VERSION
from test_ai_package_server import app, package, snapshots
from test_ai_server_runtime import basic, request, running
from ai_http_helpers import workflow_paths
from test_ai_versioned_runtime import contributions, post

def refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == '$ref':
                yield item
            yield from refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from refs(item)

@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_all_shared_documents_resolve_with_exact_sizes_and_checksums(app, package, auth):
    token = basic(auth) if auth else None
    with running(app, auth=auth) as (port, log, errors):
        payload = contributions(package)
        bodies = {}
        for prefix in ('/v1', '/v2'):

            def get(path):
                status, headers, raw = request(port, path, authorization=token)
                assert status == 200, (path, raw)
                return raw
            catalog = json.loads(get(prefix + '/api'))
            contract = json.loads(get(prefix + '/contract'))
            assert catalog['run_id'] == contract['run_id'] == package['manifest']['analysis_id']
            schema_names = {name.rsplit('/', 1)[1][:-5] for name in contract['assets'] if name.startswith('schemas/')}
            assert schema_names == set(catalog['schemas'])
            for name, entry in contract['assets'].items():
                assert entry['url'].startswith(prefix + '/')
                if auth:
                    assert request(port, entry['url'])[0] == 401
                raw = get(entry['url'])
                assert entry['checksum'] == digest(raw) and entry['bytes'] == len(raw)
                bodies[prefix, name] = raw
                if name.startswith('schemas/'):
                    schema = json.loads(raw)
                    Draft202012Validator.check_schema(schema)
                    assert all((not r.startswith('/') or r.startswith(prefix + '/') for r in refs(schema)))
                else:
                    blocks = re.findall(b'```json\\n(.*?)\\n```', raw.split(b'## Artefacts', 1)[1], re.S)
                    role = name.rsplit('/', 1)[1][:-3]
                    expected = {'analyst': ['input', 'analyst'], 'cve': ['input', 'cve'], 'reviewer': ['input', 'analyst', 'cve', 'reviewer']}[role]
                    assert len(blocks) == len(expected)
                    for block, schema_name in zip(blocks, expected):
                        assert json.loads(block) == json.loads(get(prefix + '/schema/' + schema_name))
                    text = raw.decode().split('## Artefacts', 1)[0]
                    assert 'source_chunk' not in text
            for role in ('analyst', 'cve', 'reviewer'):
                schema = json.loads(get(prefix + '/schema/' + role))
                assert schema['required'] == ['run_id', 'role', 'results']
                Draft202012Validator(schema).validate(payload[role])
            workflow = json.loads(get(prefix + '/schema/workflow'))
            assert workflow['properties'] == {r: {'$ref': prefix + '/schema/' + r} for r in payload}
            validation, _ = workflow_paths(port, prefix, token=token)
            assert post(port, validation, payload, token)[0] == 200
            assert not app.with_name(app.name + '.results').exists()
            for ref in refs(catalog):
                if ref.startswith('/'):
                    assert ref.startswith(prefix + '/')
                    if '<' not in ref:
                        get(ref)
        for name in contract['assets']:
            if name != 'schemas/workflow.json':
                assert bodies['/v1', name] == bodies['/v2', name]
        assert json.loads(get('/v1/version')) == json.loads(get('/v2/version'))

def test_extra_selected_documents_are_listed_and_served_in_both_apis(snapshots, tmp_path):
    selected = copy.deepcopy(snapshots)
    selected['prompts/notes.md'] = b'# Additional operator notes\n'
    selected['schemas/notes.json'] = b'{"type":"string"}'
    package = build_package([{'commit': 'a' * 40}], {}, selected, VERSION)
    app = tmp_path / 'serve_ai.pyz'
    generate_ai_package_server(package, b'# Entry', app)
    with running(app) as (port, log, errors):
        for prefix in ('/v1', '/v2'):
            index = json.loads(request(port, prefix + '/contract')[2])
            for group, ext in [('prompts', '.md'), ('schemas', '.json')]:
                name = group + '/notes' + ext
                entry = index['assets'][name]
                raw = request(port, entry['url'])[2]
                assert digest(raw) == entry['checksum']
                assert json.loads(raw) == {'type': 'string'} if group == 'schemas' else raw == selected[name]
            for suffix in ('/prompt/missing', '/schema/missing', '/contract/extra'):
                assert request(port, prefix + suffix)[0] == 404
