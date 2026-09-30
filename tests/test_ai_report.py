"""Tests for imported AI findings in report-only commit copies."""
import json

from lib.ai_report import attach_ai_results, load_ai_results


def test_missing_or_obsolete_results_are_ignored(tmp_path):
    assert load_ai_results(str(tmp_path)) == {}
    (tmp_path / 'ai_analysis_bundle_manifest.json').write_text(
        json.dumps({'run_id': 'current'}), encoding='utf-8')
    (tmp_path / 'ai_analysis_results.json').write_text(
        json.dumps({'run_id': 'old', 'results': {'a' * 40: {'ai_summary': 'old'}}}),
        encoding='utf-8')
    assert load_ai_results(str(tmp_path)) == {}


def test_matching_results_attach_without_mutating_scores_or_source(tmp_path):
    sha = 'a' * 40
    (tmp_path / 'ai_analysis_bundle_manifest.json').write_text(
        json.dumps({'run_id': 'current'}), encoding='utf-8')
    (tmp_path / 'ai_analysis_results.json').write_text(
        json.dumps({'run_id': 'current', 'results': {sha: {
            'ai_backport_recommendation': 'maybe', 'ai_summary': 'Needs review'}}}),
        encoding='utf-8')
    results = load_ai_results(str(tmp_path))
    commits = [{'commit': sha, 'score': 42, 'pick_priority': 71},
               {'commit': 'b' * 40, 'score': 12}]
    decorated = attach_ai_results(commits, results)
    assert [c['commit'] for c in decorated] == [c['commit'] for c in commits]
    assert decorated[0]['score'] == 42
    assert decorated[0]['pick_priority'] == 71
    assert decorated[0]['ai_analysis']['ai_backport_recommendation'] == 'maybe'
    assert 'ai_analysis' not in decorated[1]
    assert 'ai_analysis' not in commits[0]
    decorated[0]['ai_analysis']['ai_summary'] = 'changed'
    assert results[sha]['ai_summary'] == 'Needs review'
