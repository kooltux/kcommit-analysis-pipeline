"""Regression tests for AI-aware Stage 07 output decoration."""
import json

from lib.stages import st07_ai_report
from lib.stages import st07_report


def test_ai_report_keeps_bundle_and_decorates_json_and_detail(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    out = tmp_path / 'output'
    cache.mkdir()
    out.mkdir()
    sha = 'a' * 40
    source = {'commit': sha, 'score': 13, 'pick_priority': 40,
              'subject': 'Fix', 'author_time': 0}
    (cache / 'relevant_commits.json').write_text(json.dumps([source]))
    (out / 'ai_analysis_bundle_manifest.json').write_text(json.dumps({'run_id': 'run-a'}))
    (out / 'ai_analysis_results.json').write_text(json.dumps({
        'run_id': 'run-a', 'results': {sha: {'ai_summary': 'Review this fix'}}}))
    def legacy_generator(*args):
        raise AssertionError('Legacy AI generator must not run')
    def baseline(cfg, cachedir, outdir):
        st07_report._write_ai_analysis_files(cfg, cachedir, outdir)
        return {'generated_files': ['relevant_commits.json'], 'total_scored_commits': 1}
    monkeypatch.setattr(st07_report, '_write_ai_analysis_files', legacy_generator)
    monkeypatch.setattr(st07_report, 'run', baseline)
    cfg = {'reports': {'outputs': []}, 'paths': {'templates_dir': None}}
    result = st07_ai_report.run(cfg, str(cache), str(out))
    exported = json.loads((out / 'relevant_commits.json').read_text())
    detail = json.loads((out / 'commits' / 'a' / 'aa.json').read_text())
    assert exported[0]['ai_analysis']['ai_summary'] == 'Review this fix'
    assert detail[sha]['ai_analysis']['ai_summary'] == 'Review this fix'
    assert exported[0]['score'] == 13
    assert json.loads((cache / 'relevant_commits.json').read_text()) == [source]
    assert result['ai_analyzed_commits'] == 1
    assert st07_report._write_ai_analysis_files is legacy_generator


def test_stale_ai_results_do_not_decorate(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    out = tmp_path / 'output'
    cache.mkdir()
    out.mkdir()
    (out / 'ai_analysis_bundle_manifest.json').write_text(json.dumps({'run_id': 'new'}))
    (out / 'ai_analysis_results.json').write_text(json.dumps({
        'run_id': 'old', 'results': {'a' * 40: {'ai_summary': 'obsolete'}}}))
    monkeypatch.setattr(st07_report, 'run', lambda *_: {'generated_files': []})
    cfg = {'reports': {'outputs': []}, 'paths': {'templates_dir': None}}
    result = st07_ai_report.run(cfg, str(cache), str(out))
    assert result == {'generated_files': []}
    assert not (out / 'relevant_commits.json').exists()
