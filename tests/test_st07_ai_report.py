"""Regression tests for AI-aware Stage 07 output decoration."""
import json

import pytest

from lib.ai_exchange import Progress, WorkPackage
from lib.ai_import_store import publish_imported_results, read_imported_results
from lib.stages import st07_ai_report
from lib.stages import st07_report
from test_ai_batch_layout import prepare
from test_ai_import_sources import record


@pytest.mark.parametrize('layout', ['legacy', 'store'])
def test_ai_report_keeps_bundle_and_decorates_json_and_detail(tmp_path, monkeypatch, layout):
    cfg, cache, out, _, _ = prepare(tmp_path, count=1)
    package = WorkPackage(cfg, Progress('test'))
    sha = next(iter(package.by_sha))
    source = {'commit': sha, 'score': 13, 'pick_priority': 40,
              'subject': 'Fix', 'author_time': 0}
    (cache / 'relevant_commits.json').write_text(json.dumps([source]))
    item = dict(record(package), ai_summary='Review this fix')
    sidecar = out / 'ai_analysis_results.json'
    if layout == 'legacy':
        sidecar.write_text(json.dumps({'run_id': package.manifest['run_id'], 'results': {sha: item}}))
    else:
        store, _ = read_imported_results(package)
        publish_imported_results(package, store, {sha: item})
        sidecar.unlink()
    manifest_before = (out / 'ai_analysis_bundle_manifest.json').read_bytes()
    app_before = (out / 'serve_ai.pyz').read_bytes()
    sidecar_before = sidecar.read_bytes() if sidecar.exists() else None
    monkeypatch.setattr(st07_report, 'run', lambda *_: {
        'generated_files': ['relevant_commits.json'], 'total_scored_commits': 1})
    cfg['reports'] = {'outputs': []}
    cfg['paths']['templates_dir'] = None
    result = st07_ai_report.run(cfg, str(cache), str(out))
    exported = json.loads((out / 'relevant_commits.json').read_text())
    detail = json.loads((out / 'commits' / sha[0] / (sha[1:3] + '.json')).read_text())
    assert exported[0]['ai_analysis']['ai_summary'] == 'Review this fix'
    assert detail[sha]['ai_analysis']['ai_summary'] == 'Review this fix'
    assert exported[0]['score'] == 13 and exported[0]['pick_priority'] == 40
    assert json.loads((cache / 'relevant_commits.json').read_text()) == [source]
    assert result['ai_analyzed_commits'] == 1
    assert (out / 'ai_analysis_bundle_manifest.json').read_bytes() == manifest_before
    assert (out / 'serve_ai.pyz').read_bytes() == app_before
    assert (sidecar.read_bytes() if sidecar.exists() else None) == sidecar_before


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


def test_invalid_findings_fail_before_standard_reports_are_written(tmp_path, monkeypatch):
    cfg, cache, out, _, _ = prepare(tmp_path, count=1)
    package = WorkPackage(cfg, Progress('test'))
    sha = next(iter(package.by_sha))
    (out / 'ai_analysis_results.json').write_text(json.dumps({
        'run_id': package.manifest['run_id'], 'results': {sha: {'ai_summary': 'invalid'}}}))
    monkeypatch.setattr(st07_report, 'run', lambda *_: pytest.fail('report write before validation'))
    with pytest.raises(ValueError):
        st07_ai_report.run(cfg, str(cache), str(out))
