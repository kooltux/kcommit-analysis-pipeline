"""Direct acceptance comparisons for version/group independence and write boundaries."""
import copy
import csv
import io
import json
from pathlib import Path
import zipfile

import pytest

from lib.ai_canonical import record_path
from lib.ai_contract import digest
from lib.manifest import CACHE_FILES, COMMIT_COLS, COMMIT_COLS_FILTERED
from lib.stages import st07_ai_report, st07_report, st08_prepare_ai
from test_ai_package_server import app, package, snapshots
from test_ai_runtime_persistence import snapshot
from test_ai_server_runtime import request, running
from test_ai_versioned_runtime import contributions, post
from test_st08_prepare_ai import setup_source


def test_equivalent_versions_and_v2_groups_have_identical_records(app, package, tmp_path):
    documents = contributions(package)
    expected_shas = sorted(documents['analyst']['results'])
    variants = [('/v1', None), ('/v2', None), ('/v2', 1), ('/v2', 2)]
    reference = None
    plan_ids = []
    for number, (prefix, size) in enumerate(variants):
        isolated = tmp_path / str(number) / app.name
        isolated.parent.mkdir()
        isolated.write_bytes(app.read_bytes())
        root = Path(str(isolated) + '.results')
        with running(isolated) as (port, log, errors):
            groups = [expected_shas]
            if size is not None:
                response = post(port, '/v2/plan', {'max_commits': size})
                assert response[0] == 200
                plan = json.loads(response[2])
                assert plan['run_id'] == package['manifest']['analysis_id']
                plan_ids.append(plan['plan_id'])
                groups = []
                for group in plan['groups']:
                    status, _, raw = request(port, '/v2/plan/' + plan['plan_id'] + '/' + group['group_id'])
                    assert status == 200 and len(raw) == group['input_bytes']
                    source = json.loads(raw)
                    assert source['run_id'] == package['manifest']['analysis_id']
                    members = [item['commit'] for item in source['commits']]
                    assert members == group['commits']
                    groups.append(members)
                assert len(groups) == (len(expected_shas) + size - 1) // size
            for members in groups:
                supplied = {role: dict(document, results={sha: document['results'][sha] for sha in members})
                            for role, document in documents.items()}
                before, existed = snapshot(root), root.exists()
                assert post(port, prefix + '/validate/workflow', supplied)[0] == 200
                assert snapshot(root) == before and root.exists() == existed
                status, _, raw = post(port, prefix + '/result', supplied)
                assert status == 200
                receipt = json.loads(raw)['results']
                assert set(receipt) == set(members)
                for sha in members:
                    assert digest((root / record_path(sha)).read_bytes()) == receipt[sha]
            actual = {path.relative_to(root).as_posix(): path.read_bytes()
                      for path in root.rglob('*') if path.is_file()}
            assert set(actual) == {record_path(sha) for sha in expected_shas}
            for sha in expected_shas:
                status, _, raw = request(port, prefix + '/result/' + sha)
                assert status == 200 and raw == actual[record_path(sha)]
                value = json.loads(raw)
                assert set(value) == {'run_id', 'commit', 'assessment'}
                assert value['run_id'] == package['manifest']['analysis_id'] and value['commit'] == sha
                assert value['assessment'] == {key: item for document in documents.values()
                    for key, item in document['results'][sha].items()}
            status, _, exported = request(port, prefix + '/export')
            assert status == 200
            with zipfile.ZipFile(io.BytesIO(exported)) as archive:
                exported_records = {name[len('results/'):]: archive.read(name)
                                    for name in archive.namelist() if name.startswith('results/')}
            assert exported_records == actual
            if reference is None:
                reference = actual, exported
            assert (actual, exported) == reference
    assert len(set(plan_ids)) == 2


@pytest.mark.parametrize('prefix', ['/v1', '/v2'])
def test_validation_submission_parity_preserves_existing_records(app, package, prefix):
    documents = contributions(package)
    root = Path(str(app) + '.results')
    sha = sorted(documents['analyst']['results'])[0]
    candidate = copy.deepcopy(documents)
    for document in candidate.values():
        document['results'] = {sha: document['results'][sha]}
    candidate['analyst']['results'][sha]['ai_summary'] = 'Validated replacement'
    with running(app) as (port, log, errors):
        for populated in (False, True):
            if populated:
                assert post(port, prefix + '/result', documents)[0] == 200
            before, existed = snapshot(root), root.exists()
            assert existed == populated
            assert post(port, prefix + '/validate/workflow', candidate)[0] == 200
            assert snapshot(root) == before and root.exists() == existed
            for problem in ('run', 'unknown', 'field', 'fourth', 'coverage'):
                bad = copy.deepcopy(candidate)
                if problem == 'run':
                    bad['analyst']['run_id'] = 'f' * 64
                elif problem == 'unknown':
                    for document in bad.values():
                        document['results']['f' * 40] = copy.deepcopy(document['results'][sha])
                elif problem == 'field':
                    bad['analyst']['results'][sha]['ai_is_bug_fix'] = 'FALSE'
                elif problem == 'fourth':
                    bad['result'] = {}
                else:
                    bad['reviewer']['results'].pop(sha)
                for endpoint in ('/validate/workflow', '/result'):
                    assert post(port, prefix + endpoint, bad)[0] == 400
                    assert snapshot(root) == before and root.exists() == existed
        assert post(port, prefix + '/result', candidate)[0] == 200
        assert snapshot(root) != before
        for member, (raw, mtime) in before.items():
            if member != record_path(sha):
                assert snapshot(root)[member] == (raw, mtime)
        value = json.loads(request(port, prefix + '/result/' + sha)[2])
        assert value['assessment']['ai_summary'] == 'Validated replacement'


def test_no_ai_reports_repeat_and_respect_requested_formats(tmp_path, monkeypatch):
    commits = [dict(commit=letter * 40, subject='Fix', score=3-i,
                    pick_priority=20-i, _rank=i+1) for i, letter in enumerate('abc')]
    cfg, cache, out = setup_source(tmp_path, commits)
    cfg['reports'] = {'outputs': ['csv'], 'top_n': 1}
    for key, values in [('relevant', commits[:2]), ('filtered', commits[2:]),
                        ('postfilter_dropped', [])]:
        (cache / CACHE_FILES[key]).write_text(json.dumps(values))
    monkeypatch.setattr(st07_report, '_load_profile_rules_safe', lambda *_: {})
    monkeypatch.setattr(st07_report, '_copy_helper_scripts', lambda *_: [])
    monkeypatch.setattr(st07_report, '_dump_merged_config', lambda *_: None)
    def no_prepare(*args, **kwargs):
        raise AssertionError('No-AI reporting must not prepare Stage 08')
    monkeypatch.setattr(st08_prepare_ai, 'run', no_prepare)
    before = {path.relative_to(cache): path.read_bytes() for path in cache.rglob('*') if path.is_file()}
    previous = None
    for _ in range(2):
        stats = st07_ai_report.run(cfg, str(cache), str(out))
        assert stats['total_scored_commits'] == 1 and 'ai_analyzed_commits' not in stats
        for name, expected, columns in [('relevant', commits[:1], COMMIT_COLS),
                                        ('filtered', commits[2:], COMMIT_COLS_FILTERED)]:
            rows = json.loads((out / (name + '_commits.json')).read_text())
            assert [row['commit'] for row in rows] == [row['commit'] for row in expected]
            assert all('ai_analysis' not in row for row in rows)
            with (out / (name + '_commits.csv')).open(newline='', encoding='utf-8') as stream:
                table = list(csv.reader(stream))
            assert table[0] == list(columns) and len(table) == 2
            assert float(table[1][12]) == expected[0]['score']
        stable = {path.relative_to(out): path.read_bytes() for path in out.rglob('*') if path.is_file()
                  and (path.name in ('relevant_commits.json', 'filtered_commits.json',
                       'relevant_commits.csv', 'filtered_commits.csv', 'profile_matrix.json',
                       'profile_summary.json', 'rule_trace.json') or 'commits' in path.relative_to(out).parts)}
        if previous is not None:
            assert stable == previous
        previous = stable
        assert not any(path.suffix in ('.html', '.xlsx', '.ods') for path in out.rglob('*'))
        assert not (out / 'serve_ai.pyz').exists() and not (out / 'serve_report.pyz').exists()
    assert before == {path.relative_to(cache): path.read_bytes() for path in cache.rglob('*') if path.is_file()}
