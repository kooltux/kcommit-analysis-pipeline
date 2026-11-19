"""Explicit current-API clients for generated-server regression tests only."""
import json
from test_ai_server_runtime import request


def record_url(prefix, sha):
    return prefix + ('/result/commit/' if prefix == '/v2' else '/result/') + sha


def workflow_paths(port, prefix, size=2, token=None):
    if prefix == '/v1':
        return '/v1/validate/workflow', '/v1/result'
    status, _, raw = request(port, '/v2/plan?max_commits_per_group=' + str(size),
                             authorization=token)
    assert status == 200, raw
    groups = json.loads(raw)['groups']
    assert groups
    group_id = groups[0]['group_id']
    return '/v2/validate/' + group_id, '/v2/result/' + group_id


def submit_selection(port, prefix, documents, token=None):
    """Publish a valid arbitrary selection as complete single-commit v2 groups."""
    def post(path, value):
        return request(port, path, method='POST', body=json.dumps(value).encode(),
                       authorization=token)
    if prefix == '/v1':
        return post('/v1/result', documents)
    selected = set(documents['analyst']['results'])
    assert selected and all(set(doc['results']) == selected for doc in documents.values())
    status, _, raw = request(port, '/v2/plan?max_commits_per_group=1', authorization=token)
    assert status == 200, raw
    results, seen, headers = {}, set(), {}
    for group in json.loads(raw)['groups']:
        status, _, source = request(port, '/v2/group/' + group['group_id'], authorization=token)
        assert status == 200, source
        members = {item['commit'] for item in json.loads(source)['commits']}
        assert len(members) == 1
        if not members <= selected:
            continue
        body = {role: dict(doc, results={sha: doc['results'][sha] for sha in members})
                for role, doc in documents.items()}
        response = post('/v2/result/' + group['group_id'], body)
        if response[0] != 200:
            return response
        headers = response[1]
        receipt = json.loads(response[2])
        assert receipt['status'] == 'stored'
        assert receipt['run_id'] == documents['analyst']['run_id']
        assert set(receipt['results']) == members and not seen & members
        results.update(receipt['results'])
        seen.update(members)
    assert seen == selected
    return 200, headers, json.dumps(dict(status='stored',
        run_id=documents['analyst']['run_id'], results=results)).encode()
