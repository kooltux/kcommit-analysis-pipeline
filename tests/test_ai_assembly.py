"""Canonical assembly preserves specialist values and advisory review proposals."""
import copy
import json
from pathlib import Path
import pytest
from lib.ai_contract import digest
from test_ai_package_server import app, package, snapshots
from test_ai_server_runtime import basic, request, running
from test_ai_versioned_runtime import contributions, post

@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
@pytest.mark.parametrize('mode', ['complete', 'partial', 'disagree'])
def test_submission_receipt_and_preservation(app, package, auth, mode):
    documents = contributions(package)
    if mode == 'partial':
        for doc in documents.values():
            doc['results'].pop('b' * 40)
    if mode == 'disagree':
        for item in documents['reviewer']['results'].values():
            item.update(rv_agreement='disagree', rv_notes=['ai_summary: [strong] - Manual assessment -> changed (evidence)'], rv_recommendation=['ai_summary: use changed'])
    token = basic(auth) if auth else None
    with running(app, auth=auth) as (port, log, errors):
        for attempt in range(2):
            code, _, raw = post(port, '/v1/result', documents, token)
            assert code == 200, raw
            receipts = json.loads(raw)['results']
            assert set(receipts) == set(documents['analyst']['results'])
            for sha, checksum in receipts.items():
                data = request(port, '/v2/result/' + sha, authorization=token)[2]
                assert digest(data) == checksum
                expected = {key: value for doc in documents.values() for key, value in doc['results'][sha].items()}
                assert json.loads(data) == dict(run_id=package['manifest']['analysis_id'], commit=sha, assessment=expected)
        if mode == 'partial':
            assert request(port, '/v2/result/' + 'b' * 40, authorization=token)[0] == 404

@pytest.mark.parametrize('problem', ['four_documents', 'missing', 'extra', 'identity', 'field', 'coverage', 'transport'])
def test_invalid_submission_cannot_replace_results(app, package, problem):
    valid = contributions(package)
    bad = copy.deepcopy(valid)
    if problem == 'four_documents':
        bad['result'] = {}
    elif problem == 'missing':
        del bad['cve']
    elif problem == 'extra':
        bad['metadata'] = {}
    elif problem == 'identity':
        bad['analyst']['run_id'] = 'f' * 64
    elif problem == 'field':
        bad['analyst']['results']['a' * 40]['ai_is_bug_fix'] = 'yes'
    elif problem == 'transport':
        bad['analyst']['source_chunk'] = 'batch_001/001.json'
    else:
        bad['analyst']['results'] = {}
    root = Path(str(app) + '.results')
    with running(app) as (port, log, errors):
        for populated in (False, True):
            if populated:
                assert post(port, '/v1/result', valid)[0] == 200
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            for prefix in ('/v1', '/v2'):
                for endpoint in ('/result', '/validate/workflow'):
                    assert post(port, prefix + endpoint, bad)[0] == 400
            assert {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before
