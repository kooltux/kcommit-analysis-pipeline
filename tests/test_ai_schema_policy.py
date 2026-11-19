"""Generated-package HTTP acceptance policy: ignore extras, never repair known fields."""
import copy
import json
from pathlib import Path
import pytest
from ai_http_helpers import record_url, workflow_paths
from lib.ai_canonical import record_path
from test_ai_package_server import app, package, snapshots
from test_ai_runtime_persistence import snapshot
from test_ai_server_runtime import namespace, request, running
from test_ai_versioned_runtime import contributions, post


def test_strict_schema_cli_defaults_and_flag(namespace):
    parser = namespace['build_parser']()
    assert parser.parse_args([]).strict_schema is False
    assert parser.parse_args(['--strict-schema']).strict_schema is True


@pytest.mark.parametrize('prefix', ['/v1', '/v2'])
@pytest.mark.parametrize('strict', [False, True])
def test_extra_fields_policy_matches_role_validation_and_submission(app, package, prefix, strict):
    clean = contributions(package)
    supplied = copy.deepcopy(clean)
    secret = 'extra-value-must-not-appear-in-normal-logs'
    supplied['unexpected_document'] = secret
    for role in clean:
        supplied[role]['unexpected_envelope_field'] = secret
        supplied[role]['results']['a' * 40]['unexpected\nfield'] = secret
    unchanged = copy.deepcopy(supplied)
    root = Path(str(app) + '.results')
    with running(app, extra=('--strict-schema',) if strict else ()) as (port, log, errors):
        validation, submission = workflow_paths(port, prefix)
        catalog = json.loads(request(port, prefix + '/api')[2])
        assert catalog['schema_policy'] == dict(strict=strict, extra_fields='reject' if strict else 'ignore')
        assert set(catalog['planning_defaults']) == {'max_commits_per_group', 'max_bytes_per_group', 'max_groups'}
        expected = 400 if strict else 200
        for role in clean:
            assert post(port, prefix + '/validate/role/' + role, supplied[role])[0] == expected
        assert post(port, validation, supplied)[0] == expected
        assert not root.exists()
        status, _, raw = post(port, submission, clean)
        assert status == 200
        baseline = json.loads(raw)
        before = snapshot(root)
        status, _, raw = post(port, submission, supplied)
        assert status == expected
        if strict:
            assert snapshot(root) == before
        else:
            assert json.loads(raw) == baseline
            for sha in baseline['results']:
                status, _, raw = request(port, record_url(prefix, sha))
                assert status == 200
                actual = json.loads(raw)['assessment']
                assert actual == {key: value for doc in clean.values() for key, value in doc['results'][sha].items()}
            assert 'SERVER schema_filter' in log.read_text()
        assert secret not in log.read_text()
    assert supplied == unchanged


@pytest.mark.parametrize('prefix', ['/v1', '/v2'])
@pytest.mark.parametrize('strict', [False, True])
@pytest.mark.parametrize('problem', ['missing_role', 'missing_field', 'boolean', 'enum',
    'run', 'role', 'unknown_sha', 'coverage', 'review', 'cve_counts', 'array_type'])
def test_defined_errors_are_rejected_without_publication(app, package, prefix, strict, problem):
    clean = contributions(package)
    bad = copy.deepcopy(clean)
    sha = 'a' * 40
    if problem == 'missing_role':
        del bad['cve']
    elif problem == 'missing_field':
        del bad['analyst']['results'][sha]['ai_summary']
    elif problem == 'boolean':
        bad['analyst']['results'][sha]['ai_is_bug_fix'] = 'FALSE'
    elif problem == 'enum':
        bad['analyst']['results'][sha]['ai_backport_effort'] = 'unsupported'
    elif problem == 'run':
        bad['analyst']['run_id'] = 'f' * 64
    elif problem == 'role':
        bad['analyst']['role'] = 'cve'
    elif problem == 'unknown_sha':
        for doc in bad.values():
            doc['results']['f' * 40] = copy.deepcopy(doc['results'][sha])
    elif problem == 'coverage':
        bad['reviewer']['results'].pop('b' * 40)
    elif problem == 'review':
        bad['reviewer']['results'][sha].update(rv_agreement='agree', rv_notes=['invalid'], rv_recommendation=None)
    elif problem == 'cve_counts':
        bad['cve']['results'][sha].update(ai_cve_ids=[], ai_cve_probabilities=[50])
    else:
        bad['cve']['results'][sha]['ai_cve_probabilities'] = ['50']
    bad['analyst']['extra_note'] = 'must not repair a defined error'
    root = Path(str(app) + '.results')
    with running(app, extra=('--strict-schema',) if strict else ()) as (port, log, errors):
        validation, submission = workflow_paths(port, prefix)
        assert post(port, submission, clean)[0] == 200
        before = snapshot(root)
        for endpoint in (validation, submission):
            assert post(port, endpoint, bad)[0] == 400
            assert snapshot(root) == before


@pytest.mark.parametrize('strict', [False, True])
def test_canonical_storage_is_strict_in_both_http_modes(app, package, strict):
    root = Path(str(app) + '.results')
    with running(app, extra=('--strict-schema',) if strict else ()) as (port, log, errors):
        assert post(port, '/v1/result', contributions(package))[0] == 200
        path = root / record_path('a' * 40)
        record = json.loads(path.read_bytes())
        record['assessment']['unexpected'] = 'not a canonical field'
        path.write_text(json.dumps(record))
        before = snapshot(root)
        assert request(port, '/v2/result/commit/' + 'a' * 40)[0] == 500
        assert request(port, '/v2/export')[0] == 500
        assert snapshot(root) == before
