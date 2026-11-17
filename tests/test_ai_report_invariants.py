"""Report-only AI annotations preserve scope, caches and source package assets."""
import copy
import json

from lib.ai_exchange import Progress, WorkPackage
from lib.ai_import_store import publish_imported_results, read_imported_results
from lib.ai_report import attach_ai_results
from lib.manifest import CACHE_FILES
from lib.stages import st07_ai_report, st07_report, st08_prepare_ai
from test_ai_batch_layout import prepare
from test_ai_import_sources import record


def test_attachment_copies_nested_data_and_removes_stale_findings():
    commits = [{'commit': 'a' * 40, 'scoring': {'profiles': {'x': 7}}},
               {'commit': 'b' * 40, 'ai_analysis': {'ai_summary': 'stale'}}]
    results = {'a' * 40: {'ai_summary': 'current', 'rv_notes': ['proposal']}}
    before, accepted = copy.deepcopy(commits), copy.deepcopy(results)
    decorated = attach_ai_results(commits, results)
    assert 'ai_analysis' not in decorated[1]
    decorated[0]['scoring']['profiles']['x'] = 999
    decorated[0]['ai_analysis']['rv_notes'].append('display-only change')
    assert commits == before and results == accepted


def test_table_index_preserves_findings_without_inventing_missing_assessments(tmp_path):
    commits = attach_ai_results([{'commit': 'a' * 40}, {'commit': 'b' * 40}],
                               {'a' * 40: {'ai_summary': 'Review', 'ai_is_bug_fix': False}})
    path = tmp_path / 'table.json'
    st07_report._write_table_json(str(path), commits)
    rows = json.loads(path.read_text())
    assert rows[0]['ai_analysis'] == commits[0]['ai_analysis']
    assert 'ai_analysis' not in rows[1]


def test_single_pass_preserves_top_n_filtered_membership_scores_caches_and_bundle(tmp_path, monkeypatch):
    cfg, cache, out, _, _ = prepare(tmp_path, count=5)
    package = WorkPackage(cfg, Progress('test'))
    shas = sorted(package.by_sha)
    commits = [dict(commit=sha, subject='Fix ' + str(i), score=10-i,
                    pick_priority=40-i, _rank=i+1, scoring={'profiles': {'x': 10-i}},
                    matched_profiles=['x']) for i, sha in enumerate(shas)]
    for key, values in [('relevant', commits[:3]), ('filtered', [commits[3]]),
                        ('postfilter_dropped', [dict(commits[4], _filter_reason='score')])]:
        (cache / CACHE_FILES[key]).write_text(json.dumps(values))
    cfg['reports'] = {'outputs': [], 'top_n': 2}
    monkeypatch.setattr(st07_report, '_load_profile_rules_safe', lambda *_: {})
    monkeypatch.setattr(st07_report, '_copy_helper_scripts', lambda *_: [])
    monkeypatch.setattr(st07_report, '_dump_merged_config', lambda *_: None)
    baseline_stats = st07_report.run(cfg, str(cache), str(out))
    baseline = {name: json.loads((out / (name + '_commits.json')).read_text())
                for name in ('relevant', 'filtered')}
    item = dict(record(package), ai_summary='Advisory finding')
    store, _ = read_imported_results(package)
    publish_imported_results(package, store, {sha: item for sha in (shas[0], shas[2], shas[3])})
    cache_before = {p.relative_to(cache): p.read_bytes() for p in cache.rglob('*') if p.is_file()}
    protected = {name: (out / name).read_bytes() for name in
                 ('ai_analysis_bundle_manifest.json', 'serve_ai.pyz', 'ai_analysis_results.json')}
    def no_prepare(*_):
        raise AssertionError('Stage 08 must not run during reports')
    monkeypatch.setattr(st08_prepare_ai, 'run', no_prepare)
    original, calls = st07_report.run, []
    def once(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(st07_report, 'run', once)
    stats = st07_ai_report.run(cfg, str(cache), str(out))
    assert len(calls) == 1 and len(calls[0]) == 4
    assert stats['ai_analyzed_commits'] == 3 and stats['ai_reported_commits'] == 2
    assert {k: v for k, v in stats.items() if not k.startswith('ai_')} == baseline_stats
    for name in ('relevant', 'filtered'):
        rows = json.loads((out / (name + '_commits.json')).read_text())
        assert [{k: v for k, v in row.items() if k != 'ai_analysis'} for row in rows] == baseline[name]
        assert 'ai_analysis' in rows[0] and 'ai_analysis' not in rows[1]
    assert not any(shas[2] in json.loads(p.read_text()) for p in (out / 'commits').rglob('*.json'))
    assert cache_before == {p.relative_to(cache): p.read_bytes() for p in cache.rglob('*') if p.is_file()}
    assert all((out / name).read_bytes() == data for name, data in protected.items())
