"""Exercise versioned delivery against real isolated, stdlib-only zipapps."""
import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

import lib.ai_canonical as canonical
import lib.ai_planning as planning
from lib.ai_contract import digest, result_properties
from test_ai_import_sources import record as assessment
from test_ai_package_server import app, package, snapshots
from test_ai_server_runtime import basic, request, running
from ai_http_helpers import record_url, workflow_paths


def contributions(package):
    schemas = {role: json.loads(package['files']['ai_contract/schemas/' + role + '.json'])
               for role in canonical.ROLES + ('result',)}
    item = assessment(SimpleNamespace(schema=schemas['result']))
    return {role: dict(run_id=package['manifest']['analysis_id'], role=role,
                       results={sha: {key: copy.deepcopy(item[key])
                                      for key in result_properties(schemas[role])}
                                for sha in ('a' * 40, 'b' * 40)})
            for role in canonical.ROLES}


def post(port, path, value, token=None):
    return request(port, path, method='POST', body=json.dumps(value).encode(), authorization=token)


def test_shared_core_is_packaged_verbatim(app):
    with zipfile.ZipFile(app) as bundle:
        assert bundle.read('kcap_ai_runtime/canonical.py') == Path(canonical.__file__).read_bytes()
        assert bundle.read('kcap_ai_runtime/planning.py') == Path(planning.__file__).read_bytes()


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_versioned_validation_submission_retrieval_and_export_share_one_store(app, package, auth):
    root = Path(str(app) + '.results')
    documents = contributions(package)
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        for prefix in ('/v1', '/v2'):
            if auth:
                assert request(port, prefix + '/api')[0] == 401
            status, _, data = request(port, prefix + '/api', authorization=token)
            assert status == 200
            catalog = json.loads(data)
            assert catalog['run_id'] == package['manifest']['analysis_id']
            assert all(route['path'] == prefix or route['path'].startswith(prefix + '/')
                       for route in catalog['routes'])
            validation, _ = workflow_paths(port, prefix, token=token)
            assert post(port, validation, documents, token)[0] == 200
        assert not root.exists()
        status, _, data = post(port, '/v1/result', documents, token)
        assert status == 200
        receipt = json.loads(data)
        for sha in ('a' * 40, 'b' * 40):
            status, _, data = request(port, record_url('/v2', sha), authorization=token)
            assert status == 200 and digest(data) == receipt['results'][sha]
            assert set(json.loads(data)) == {'run_id', 'commit', 'assessment'}
            assert (root / canonical.record_path(sha)).read_bytes() == data
        changed = copy.deepcopy(documents)
        changed['analyst']['results']['a' * 40]['ai_summary'] = 'Updated assessment'
        for role in canonical.ROLES:
            changed[role]['results'].pop('b' * 40)
        _, submission = workflow_paths(port, '/v2', size=1, token=token)
        assert post(port, submission, changed, token)[0] == 200
        data = request(port, '/v1/result/' + 'a' * 40, authorization=token)[2]
        assert json.loads(data)['assessment']['ai_summary'] == 'Updated assessment'
        assert digest(request(port, '/v1/result/' + 'b' * 40, authorization=token)[2]) == receipt['results']['b' * 40]
        first = request(port, '/v1/export', authorization=token)
        second = request(port, '/v2/export', authorization=token)
        assert first[0] == second[0] == 200 and first[2] == second[2]
        with zipfile.ZipFile(io.BytesIO(first[2])) as bundle:
            assert 'ai_analysis_bundle_manifest.json' in bundle.namelist()
            for sha in ('a' * 40, 'b' * 40):
                assert bundle.read('results/' + canonical.record_path(sha)) == (root / canonical.record_path(sha)).read_bytes()


@pytest.mark.parametrize('problem', ['fourth', 'run', 'unknown', 'coverage', 'field'])
def test_both_workflow_gates_reject_invalid_input_without_publication(app, package, problem):
    value = contributions(package)
    if problem == 'fourth':
        value['result'] = {}
    elif problem == 'run':
        value['analyst']['run_id'] = 'f' * 64
    elif problem == 'unknown':
        for role in canonical.ROLES:
            value[role]['results']['f' * 40] = copy.deepcopy(value[role]['results']['a' * 40])
    elif problem == 'coverage':
        value['reviewer']['results'].pop('a' * 40)
    else:
        value['analyst']['results']['a' * 40]['ai_is_bug_fix'] = 'FALSE'
    with running(app, extra=('--strict-schema',)) as (port, log, errors):
        for prefix in ('/v1', '/v2'):
            for endpoint in workflow_paths(port, prefix):
                assert post(port, endpoint, value)[0] == 400
    assert not Path(str(app) + '.results').exists()


def test_v1_packaged_sources_and_v2_cached_groups_use_same_identity(app, package):
    with running(app) as (port, log, errors):
        listing = json.loads(request(port, '/v1/chunks')[2])
        one = request(port, '/v2/plan?max_commits_per_group=1')
        two = request(port, '/v2/plan?max_commits_per_group=2')
        assert one[0] == two[0] == 200
        plan = json.loads(one[2])
        assert request(port, '/v2/plan?max_commits_per_group=1')[2] == one[2]
        assert len(plan['groups']) == 2 and len(json.loads(two[2])['groups']) == 1
        physical = [json.loads(request(port, entry['url'])[2]) for entry in listing['chunks']]
        planned = []
        for group in plan['groups']:
            path = '/v2/group/' + group['group_id']
            status, _, data = request(port, path)
            assert status == 200 and len(data) == group['input_bytes']
            planned.append(json.loads(data))
        assert physical == planned
        assert all(value['run_id'] == package['manifest']['analysis_id'] for value in planned)
        assert request(port, '/v2/plan?max_bytes_per_group=1')[0] == 400
        assert request(port, '/v2/plan?commits=' + 'f' * 40)[0] == 400
        assert request(port, '/v2/plan/' + 'f' * 64)[0] == 404
        assert request(port, '/v2/plan/' + plan['plan_id'])[0] == 404
        assert json.loads(request(port, '/v2/plan?max_commits_per_group=1')[2]) == plan
    assert not Path(str(app) + '.results').exists()
