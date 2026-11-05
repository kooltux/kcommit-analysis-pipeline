"""Submission assembles, stores and returns an exact-byte checksum receipt."""
import copy
import json

import pytest

from lib.ai_contract import digest, encode
from test_ai_package_server import app, package, snapshots, workflow
from test_ai_server_runtime import basic, request, running


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
@pytest.mark.parametrize('mode', ['complete', 'partial', 'disagree'])
def test_submission_receipt_and_preservation(app, workflow, auth, mode):
    name, documents = workflow
    if mode == 'partial':
        for document in documents.values():
            document['results'] = {}
        documents['result'].update(analysis_status='partial', analyzed_commits=0)
    elif mode == 'disagree':
        for role in ('reviewer', 'result'):
            for record in documents[role]['results'].values():
                record.update(rv_agreement='disagree',
                    rv_notes=['ai_summary: [strong] - evidence -> changed (evidence)'],
                    rv_recommendation=['ai_summary: use changed'])
    inputs = {role: documents[role] for role in ('analyst', 'cve', 'reviewer')}
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        path = '/result/' + name
        if auth:
            assert request(port, path, method='POST', body=encode(inputs))[0] == 401
        for attempt in range(2):
            status, _, body = request(port, path, method='POST', body=encode(inputs), authorization=token)
            assert status == 200, body
            stored = request(port, path, authorization=token)[2]
            assert stored == encode(documents['result'])
            assert json.loads(body) == dict(status='stored', source_chunk=name,
                run_id=documents['result']['run_id'], result_checksum=digest(stored))
        routes = json.loads(request(port, '/api', authorization=token)[2])['routes']
        assert not any(entry['path'].startswith(('/metadata', '/assemble')) for entry in routes)
        for removed in ('/metadata/' + name, '/assemble/' + name):
            assert request(port, removed, authorization=token)[0] == 404
            assert request(port, removed, method='POST', body=b'{}', authorization=token)[0] == 404


@pytest.mark.parametrize('problem', ['legacy', 'four_documents', 'missing', 'extra', 'identity', 'field', 'coverage'])
def test_invalid_submission_cannot_create_or_replace_results(app, workflow, problem):
    name, documents = workflow
    inputs = {role: documents[role] for role in ('analyst', 'cve', 'reviewer')}
    invalid = copy.deepcopy(inputs)
    if problem == 'legacy':
        invalid = documents['result']
    elif problem == 'four_documents':
        invalid = documents
    elif problem == 'missing':
        del invalid['cve']
    elif problem == 'extra':
        invalid['metadata'] = {}
    elif problem == 'identity':
        invalid['analyst']['run_id'] = 'f' * 64
    elif problem == 'field':
        next(iter(invalid['analyst']['results'].values()))['ai_is_bug_fix'] = 'yes'
    else:
        invalid['analyst']['results'] = {}
    with running(app) as (port, log, errors):
        path = '/result/' + name
        assert request(port, path, method='POST', body=encode(invalid))[0] == 400
        assert request(port, path)[0] == 404
        assert not app.with_name(app.name + '.results').exists()
        assert request(port, path, method='POST', body=encode(inputs))[0] == 200
        original = request(port, path)[2]
        assert request(port, path, method='POST', body=encode(invalid))[0] == 400
        assert request(port, path)[2] == original
        assert request(port, '/result/batch_999/999.json', method='POST', body=b'{}')[0] == 404
