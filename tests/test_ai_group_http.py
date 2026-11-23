"""Generated-package HTTP coverage for durable group-ID-only v2 delivery."""
import json
from test_ai_package_server import app, package, snapshots
from test_ai_server_runtime import request, running
from test_ai_versioned_runtime import contributions, post


def test_plan_group_submit_and_restart(app, package):
    with running(app) as (port, log, errors):
        status, _, raw = request(port, '/v2/plan?max_commits_per_group=2')
        assert status == 200
        plan = json.loads(raw)
        assert plan['total_groups'] == plan['returned_groups'] == 1
        group_id = plan['groups'][0]['group_id']
        status, _, raw = request(port, '/v2/group/' + group_id)
        assert status == 200
        source = json.loads(raw)
        assert {item['commit'] for item in source['commits']} == {'a' * 40, 'b' * 40}
        documents = contributions(package)
        assert post(port, '/v2/result/' + group_id, documents)[0] == 200
        for sha in ('a' * 40, 'b' * 40):
            assert request(port, '/v2/result/commit/' + sha)[0] == 200
        for role in documents:
            documents[role]['results'].pop('b' * 40)
        assert post(port, '/v2/result/' + group_id, documents)[0] == 400
    with running(app) as (port, log, errors):
        assert json.loads(request(port, '/v2/group/' + group_id)[2]) == source


def test_group_cap_invalid_parameters_and_removed_routes(app):
    with running(app) as (port, log, errors):
        full = json.loads(request(port, '/v2/plan?max_commits_per_group=1')[2])
        part = json.loads(request(port, '/v2/plan?max_commits_per_group=1&max_groups=1')[2])
        assert part['groups'] == full['groups'][:1]
        assert part['total_groups'] == 2 and part['returned_groups'] == 1 and part['limited']
        for query in ('max_groups=-1', 'max_groups=abc', 'max_commits=1', 'commits=abc',
                      'max_groups=1&max_groups=2', 'max_bytes_per_group=1'):
            assert request(port, '/v2/plan?' + query)[0] == 400
        assert post(port, '/v2/plan', {})[0] == 405
        assert post(port, '/v2/result', {})[0] == 404
        assert request(port, '/v2/plan/' + full['plan_id'])[0] == 404
        assert request(port, '/v2/group/' + 'f' * 64)[0] == 404


def test_zero_and_empty_plan_parameters_use_defaults(app):
    with running(app) as (port, log, errors):
        status, _, raw = request(port, '/v2/plan')
        assert status == 200
        expected = json.loads(raw)
        assert expected['parameters'] == dict(max_commits_per_group=25,
                                            max_bytes_per_group=262144, max_groups=None)
        assert not expected['limited']
        names = ('max_commits_per_group', 'max_bytes_per_group', 'max_groups')
        queries = [name + '=' + value for name in names for value in ('', '0')]
        queries += ['&'.join(name + '=' + value for name in names) for value in ('', '0')]
        for query in queries:
            status, _, raw = request(port, '/v2/plan?' + query)
            assert status == 200
            assert json.loads(raw) == expected
