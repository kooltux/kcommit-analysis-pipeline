"""Canonical runtime reads are write-free and accepted records survive restarts."""
import json
from pathlib import Path
import pytest
from lib.ai_canonical import record_path
from test_ai_package_server import app, package, snapshots
from test_ai_server_runtime import basic, request, running
from ai_http_helpers import record_url
from test_ai_versioned_runtime import contributions, post

def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}

@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_canonical_reads_and_exports_are_write_free_after_restart(app, package, auth):
    root = Path(str(app) + '.results')
    token = basic(auth) if auth else None
    with running(app, auth=auth) as (port, log, errors):
        assert post(port, '/v1/result', contributions(package), token)[0] == 200
        before = snapshot(root)
        for prefix in ('/v1', '/v2'):
            for sha in ('a' * 40, 'b' * 40):
                status, _, raw = request(port, record_url(prefix, sha), authorization=token)
                assert status == 200 and raw == before[record_path(sha)][0]
            assert request(port, prefix + '/export', authorization=token)[0] == 200
        assert snapshot(root) == before
    with running(app, auth=auth) as (port, log, errors):
        status, _, raw = request(port, record_url('/v2', 'a' * 40), authorization=token)
        assert status == 200 and raw == before[record_path('a' * 40)][0]
        assert snapshot(root) == before

@pytest.mark.parametrize('problem', ['syntax', 'field', 'sha'])
def test_invalid_canonical_records_are_not_silently_exported(app, package, problem):
    root = Path(str(app) + '.results')
    with running(app) as (port, log, errors):
        assert post(port, '/v1/result', contributions(package))[0] == 200
        path = root / record_path('a' * 40)
        value = json.loads(path.read_bytes())
        if problem == 'field':
            value['assessment']['ai_is_bug_fix'] = 'FALSE'
        if problem == 'sha':
            value['commit'] = 'b' * 40
        path.write_bytes(b'broken JSON' if problem == 'syntax' else json.dumps(value).encode())
        before = snapshot(root)
        assert request(port, record_url('/v2', 'a' * 40))[0] == 500
        assert request(port, '/v2/export')[0] == 500
        assert snapshot(root) == before
