"""Live versioned reads and submission migrate validated legacy stores safely."""
import copy
import io
import json
from pathlib import Path
import zipfile

import pytest

from lib.ai_canonical import record_path
from lib.ai_contract import digest, encode
from test_ai_package_server import app, package, workflow, snapshots
from test_ai_server_runtime import basic, request, running
from test_ai_versioned_runtime import contributions, post


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


def seed(app, workflow, layout, port, token=None):
    root = Path(str(app) + '.results')
    name, documents = workflow
    if layout == 'flat':
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encode(documents['result']))
    else:
        value = {role: documents[role] for role in ('analyst', 'cve', 'reviewer')}
        assert post(port, '/result/' + name, value, token)[0] == 200
    return root


@pytest.mark.parametrize('layout', ['flat', 'indexed'])
@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_versioned_reads_are_write_free_and_submission_migrates_legacy(app, package, workflow, layout, auth):
    sha, other = 'a' * 40, 'b' * 40
    documents = contributions(package)
    incoming = copy.deepcopy(documents)
    for document in incoming.values():
        document['results'].pop(sha)
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        root = seed(app, workflow, layout, port, token)
        before = snapshot(root)
        for prefix in ('/v1', '/v2'):
            status, _, raw = request(port, prefix + '/result/' + sha, authorization=token)
            assert status == 200
            value = json.loads(raw)
            assert value == dict(run_id=package['manifest']['analysis_id'], commit=sha,
                                 assessment=workflow[1]['result']['results'][sha])
            assert request(port, prefix + '/result/' + other, authorization=token)[0] == 404
            assert post(port, prefix + '/validate/workflow', documents, token)[0] == 200
            invalid = copy.deepcopy(documents)
            invalid['analyst']['run_id'] = 'f' * 64
            assert post(port, prefix + '/result', invalid, token)[0] == 400
            status, _, exported = request(port, prefix + '/export', authorization=token)
            assert status == 200
            with zipfile.ZipFile(io.BytesIO(exported)) as bundle:
                assert bundle.read('results/' + record_path(sha)) == raw
            assert snapshot(root) == before
        assert request(port, '/v1/export', authorization=token)[2] == exported
        status, _, raw = post(port, '/v2/result', incoming, token)
        assert status == 200
        receipt = json.loads(raw)
        assert set(receipt['results']) == {other}
        for commit in (sha, other):
            path = root / record_path(commit)
            assert path.is_file()
            assert request(port, '/v1/result/' + commit, authorization=token)[2] == path.read_bytes()
        assert digest((root / record_path(other)).read_bytes()) == receipt['results'][other]
        assert all(snapshot(root)[name] == value for name, value in before.items())
        # A fully migrated canonical record no longer depends on its legacy index.
        stale = root / workflow[0] if layout == 'flat' else next((root / 'runs').glob('*/chunks/*.json'))
        stale.write_bytes(b'broken legacy data')
        assert request(port, '/v2/result/' + sha, authorization=token)[0] == 200
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        assert request(port, '/v2/result/' + sha, authorization=token)[0] == 200
        assert request(port, '/v2/export', authorization=token)[0] == 200


@pytest.mark.parametrize('problem', ['run', 'unknown', 'field', 'checksum'])
def test_invalid_legacy_findings_never_migrate_or_publish_new_records(app, package, workflow, problem):
    with running(app) as (port, log, errors):
        root = seed(app, workflow, 'indexed' if problem == 'checksum' else 'flat', port)
        if problem == 'checksum':
            path = next((root / 'runs').glob('*/commits/*/*/*.json'))
            path.write_bytes(b'{}')
        else:
            value = copy.deepcopy(workflow[1]['result'])
            if problem == 'run':
                value['run_id'] = 'f' * 64
            elif problem == 'unknown':
                value['results']['f' * 40] = value['results'].pop('a' * 40)
            else:
                value['results']['a' * 40]['ai_is_bug_fix'] = 'FALSE'
            (root / workflow[0]).write_bytes(encode(value))
        before = snapshot(root)
        documents = contributions(package)
        for document in documents.values():
            document['results'].pop('a' * 40)
        for prefix in ('/v1', '/v2'):
            assert request(port, prefix + '/result/' + 'a' * 40)[0] == 500
            assert request(port, prefix + '/export')[0] == 500
            assert post(port, prefix + '/result', documents)[0] == 500
            assert snapshot(root) == before
            assert not (root / record_path('b' * 40)).exists()


def test_partial_migration_merges_canonical_and_legacy_findings(app, package, workflow):
    sha, other = 'a' * 40, 'b' * 40
    documents = contributions(package)
    assessment = {key: value for document in documents.values()
                  for key, value in document['results'][other].items()}
    with running(app) as (port, log, errors):
        root = seed(app, workflow, 'flat', port)
        path = root / record_path(other)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encode(dict(run_id=package['manifest']['analysis_id'],
                                    commit=other, assessment=assessment)))
        before = snapshot(root)
        assert request(port, '/v1/result/' + other)[0] == 200
        assert request(port, '/v2/result/' + sha)[0] == 200
        assert snapshot(root) == before
        for document in documents.values():
            document['results'].pop(other)
        assert post(port, '/v1/result', documents)[0] == 200
        assert (root / record_path(sha)).is_file()
        assert json.loads(request(port, '/v2/result/' + other)[2])['assessment'] == assessment
        assert (root / workflow[0]).read_bytes() == before[workflow[0]][0]
        assert snapshot(root)[record_path(other)] == before[record_path(other)]
