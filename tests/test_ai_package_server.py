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
from lib.manifest import VERSION
from test_ai_preparation import snapshots
from test_ai_server_runtime import basic, request, running

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


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_contract_discovery_and_trusted_metadata(app, package, auth):
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        if auth:
            assert request(port, '/contract')[0] == 401
            assert request(port, '/prompt/analyst')[0] == 401
        def get(path):
            code, headers, data = request(port, path, authorization=token)
            assert code == 200, data
            return data
        manifest = package['manifest']
        index = json.loads(get('/contract'))
        assert index['run_id'] == manifest['run_id']
        for name, entry in index['assets'].items():
            data = get(entry['url'])
            assert data == package['files']['ai_contract/' + name]
            assert digest(data) == entry['checksum'] == manifest['contract_assets'][name]
        name = next(iter(manifest['chunks']))
        metadata = json.loads(get(index['chunks'][name]))
        assert metadata['input_checksum'] == digest(package['files']['ai_analysis_input/' + name])
        assert metadata['output_schema_checksum'] == manifest['output_schema_checksum']
        assert metadata['total_commits'] == 1
        routes = json.loads(get('/api'))['routes']
        assert {'/contract', '/metadata/<name>', '/prompt/<role>', '/schema/<role>'} <= {
            item['path'] for item in routes}
        assert get('/') == PAGE
        for path in ['/prompt/unknown', '/schema/unknown', '/metadata/batch_999/999.json']:
            assert request(port, path, authorization=token)[0] == 404


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


def test_metadata_can_drive_final_upload_and_export(app, package):
    schema = json.loads(package['files']['ai_analysis_result_schema.json'])
    record = {}
    for key, spec in result_properties(schema).items():
        kind = spec['type']
        record[key] = (None if isinstance(kind, list) else False if kind == 'boolean'
                       else [] if kind == 'array' else spec.get('enum', ['evidence'])[0])
    record.update(rv_agreement='agree', ai_risks_if_not_backported=['none'])
    with running(app) as (port, log, errors):
        name = next(iter(package['manifest']['chunks']))
        metadata = json.loads(request(port, '/metadata/' + name)[2])
        result = dict(metadata, analysis_status='complete', analyzed_commits=1, results={'a' * 40: record})
        assert request(port, '/result/' + name, method='POST', body=encode(result))[0] == 200
        status, _, data = request(port, '/export')
        assert status == 200
        with zipfile.ZipFile(io.BytesIO(data)) as exported:
            assert exported.read('results/' + name) == encode(result)
            assert exported.read('ai_analysis_bundle_manifest.json') == package['files']['ai_analysis_bundle_manifest.json']


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
        documents[role] = dict(final, role=role, results={sha: {key: item[key] for key in fields}})
    return name, documents


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_validation_routes_are_discoverable_authenticated_and_write_free(app, workflow, auth):
    name, documents = workflow
    original = app.read_bytes()
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        routes = {item['path']: item for item in json.loads(request(port, '/api', authorization=token)[2])['routes']}
        for path in ('/validate/role/<role>/<name>', '/validate/workflow/<name>'):
            assert routes[path]['method'] == 'POST'
            assert routes[path]['max_body_bytes'] == 10 * 1024 * 1024
            assert routes[path]['writes_results'] is False
        for role, document in documents.items():
            if role == 'result':
                continue
            path = '/validate/role/' + role + '/' + name
            if auth:
                assert request(port, path, method='POST', body=encode(document))[0] == 401
            code, _, data = request(port, path, method='POST', body=encode(document), authorization=token)
            assert code == 200
            assert json.loads(data)['status'] == 'valid'
        path = '/validate/workflow/' + name
        if auth:
            assert request(port, path, method='POST', body=encode(documents))[0] == 401
        code, _, data = request(port, path, method='POST', body=encode(documents), authorization=token)
        assert code == 200
        assert json.loads(data) == dict(status='valid', run_id=documents['result']['run_id'], source_chunk=name)
        for path in ['/validate/role/assembler/' + name, '/validate/workflow/batch_999/999.json']:
            assert request(port, path, method='POST', body=b'{}', authorization=token)[0] == 404
        assert request(port, '/result/' + name, authorization=token)[0] == 404
    assert app.read_bytes() == original
    assert not app.with_name(app.name + '.results').exists()


@pytest.mark.parametrize('role', ['analyst', 'cve', 'reviewer', 'result'])
@pytest.mark.parametrize('field', ['run_id', 'source_chunk', 'input_checksum', 'input_schema_checksum', 'output_schema_checksum'])
def test_workflow_rejects_mixed_identities(app, workflow, role, field):
    name, documents = workflow
    documents[role][field] = 'untrusted'
    with running(app) as (port, log, errors):
        assert request(port, '/validate/workflow/' + name, method='POST', body=encode(documents))[0] == 400
    assert not app.with_name(app.name + '.results').exists()


@pytest.mark.parametrize('problem', ['assembly', 'specialist', 'review', 'sha', 'role', 'field', 'extra_context'])
def test_workflow_rejects_invalid_contributions_without_replacing_results(app, workflow, problem):
    name, documents = workflow
    sha = next(iter(documents['result']['results']))
    with running(app) as (port, log, errors):
        original = encode(documents['result'])
        assert request(port, '/result/' + name, method='POST', body=original)[0] == 200
        if problem == 'assembly':
            documents['result']['results'][sha]['ai_summary'] = 'rewritten'
        elif problem in ('specialist', 'review'):
            role = 'analyst' if problem == 'specialist' else 'reviewer'
            documents[role].update(results={}, analyzed_commits=0, analysis_status='partial')
        elif problem == 'sha':
            documents['reviewer']['results']['f' * 40] = documents['reviewer']['results'].pop(sha)
        elif problem == 'role':
            documents['analyst']['role'] = 'cve'
        elif problem == 'field':
            documents['analyst']['results'][sha]['ai_is_bug_fix'] = 'yes'
        else:
            documents['schemas'] = {}
        assert request(port, '/validate/workflow/' + name, method='POST', body=encode(documents))[0] == 400
        assert request(port, '/result/' + name)[2] == original


@pytest.mark.parametrize('mode', ['partial', 'disagree'])
def test_workflow_accepts_partial_and_preserves_advisory_review(app, workflow, mode):
    name, documents = workflow
    if mode == 'partial':
        for document in documents.values():
            document.update(results={}, analyzed_commits=0, analysis_status='partial')
    else:
        for role in ('reviewer', 'result'):
            for record in documents[role]['results'].values():
                record.update(rv_agreement='disagree',
                    rv_notes=['ai_summary: [strong] - evidence -> changed (evidence)'],
                    rv_recommendation=['ai_summary: use changed'])
    with running(app) as (port, log, errors):
        assert request(port, '/validate/workflow/' + name, method='POST', body=encode(documents))[0] == 200
    assert not app.with_name(app.name + '.results').exists()


@pytest.mark.parametrize('route', ['role/analyst', 'workflow'])
@pytest.mark.parametrize('body', [b'{', b'\xff', b'{"x":1,"x":2}', b'{"x":NaN}', b'null', b'[]'])
def test_validation_rejects_malformed_json(app, workflow, route, body):
    name, _ = workflow
    with running(app) as (port, log, errors):
        assert request(port, '/validate/' + route + '/' + name, method='POST', body=body)[0] == 400
    assert not app.with_name(app.name + '.results').exists()


@pytest.mark.parametrize('length,transfer', [('0', None), ('-1', None), ('10485761', None),
                                           ('bad', None), ('2', 'chunked'), ('duplicate', None), ('missing', None)])
def test_validation_rejects_invalid_framing(app, workflow, length, transfer):
    import http.client
    name, _ = workflow
    with running(app) as (port, log, errors):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        try:
            connection.putrequest('POST', '/validate/workflow/' + name)
            if length == 'duplicate':
                connection.putheader('Content-Length', '2')
                connection.putheader('Content-Length', '2')
            elif length != 'missing':
                connection.putheader('Content-Length', length)
            if transfer:
                connection.putheader('Transfer-Encoding', transfer)
            connection.endheaders(b'{}')
            response = connection.getresponse()
            assert response.status == 400
            response.read()
        finally:
            connection.close()



def test_api_examples_are_live_and_metadata_usage_is_explicit(app, package):
    with running(app) as (port, log, errors):
        catalog = json.loads(request(port, '/api')[2])
        entries = {entry['path']: entry for entry in catalog['routes']}
        groups = [catalog['groups'].index(entry['group']) for entry in catalog['routes']]
        assert groups == sorted(groups)
        assert not any(entry['path'] == '/schema/output' for entry in catalog['routes'])
        assert request(port, '/schema/output')[0] == 404
        assert request(port, '/metadata')[0] == 404
        for group, path in [('prompts', '/prompt/<role>'), ('schemas', '/schema/<role>')]:
            expected = sorted(name.split('/')[1].rsplit('.', 1)[0]
                              for name in package['manifest']['contract_assets'] if name.startswith(group + '/'))
            assert entries[path]['path_parameters']['role']['enum'] == expected
        metadata = entries['/metadata/<name>']
        name = metadata['path_parameters']['name']['example']
        assert name in package['manifest']['chunks']
        assert 'trusted envelope' in metadata['description']
        data = json.loads(request(port, metadata['examples'][0]['url'])[2])
        assert data['input_checksum'] == package['manifest']['chunks'][name]
        for entry in catalog['routes']:
            for example in entry['examples']:
                assert set(example) == {'method', 'url'}
                assert '<' not in example['url']
                if entry['method'] == 'GET' and entry['path'] != '/result/<name>':
                    assert request(port, example['url'])[0] == 200
        assert entries['/validate/role/<role>/<name>']['examples'] == [
            {'method': 'POST', 'url': '/validate/role/analyst/' + name}]
        assert entries['/validate/workflow/<name>']['examples'] == [
            {'method': 'POST', 'url': '/validate/workflow/' + name}]
    assert not app.with_name(app.name + '.results').exists()



def test_validation_body_contracts_describe_complete_documents(app, workflow):
    name, documents = workflow
    with running(app) as (port, log, errors):
        entries = {entry['path']: entry for entry in json.loads(request(port, '/api')[2])['routes']}
        role = entries['/validate/role/<role>/<name>']
        assembly = entries['/validate/workflow/<name>']
        assert role['description'] != assembly['description']
        assert 'POST body' in role['description'] and 'POST body' in assembly['description']
        for entry in (role, assembly):
            assert entry['request_body']['required'] is True
            assert entry['request_body']['content_type'] == 'application/json'
            assert all(set(example) == {'method', 'url'} for example in entry['examples'])
        assert role['request_body']['schema'] == {'$ref': '/schema/<role>'}
        for value in role['roles']:
            reference = role['request_body']['schema']['$ref'].replace('<role>', value)
            assert request(port, reference)[0] == 200
            assert request(port, '/validate/role/' + value + '/' + name,
                           method='POST', body=encode(documents[value]))[0] == 200
        schema = assembly['request_body']['schema']
        assert schema['type'] == 'object'
        assert schema['required'] == assembly['document_roles']
        assert set(schema['required']) == set(documents)
        assert schema['additionalProperties'] is False
        assert schema['properties'] == {value: {'$ref': '/schema/' + value} for value in documents}
        for property_schema in schema['properties'].values():
            assert request(port, property_schema['$ref'])[0] == 200
        assert request(port, assembly['examples'][0]['url'], method='POST', body=encode(documents))[0] == 200
        assert request(port, '/result/' + name)[0] == 404
    assert not app.with_name(app.name + '.results').exists()
