"""Live canonical exports reach real reports without changing deterministic analysis."""
import copy
import csv
import json

import pytest
from openpyxl import load_workbook

from lib.ai_canonical import record_path
from lib.ai_contract import digest, encode, result_properties
from lib.ai_exchange import Progress, WorkPackage
from lib.ai_import_store import STORE_DIRECTORY
from lib.ai_report import load_ai_results
from lib.commands.cmd_ai_import import import_results
from lib.manifest import CACHE_FILES, COMMIT_COLS, COMMIT_COLS_FILTERED
from lib.stages import st07_report, st08_prepare_ai
from test_ai_batch_layout import prepare
from test_ai_report_tables import assert_summary, ods_tables, rows
from test_ai_server_runtime import request, running


@pytest.mark.parametrize('prefix', ['/v1', '/v2'])
def test_live_export_import_generates_real_reports(tmp_path, monkeypatch, rows, prefix):
    cfg, cache, out, _, _ = prepare(tmp_path, count=5)
    source = WorkPackage(cfg, Progress('acceptance'))
    shas = sorted(source.by_sha)
    commits = [dict(commit=sha, subject='Fix', score=11-i, pick_priority=30-i,
                    _rank=i+1, _filter_reason='score', matched_profiles=['x'],
                    scoring={'profiles': {'x': 11-i}}) for i, sha in enumerate(shas)]
    for key, values in [('relevant', commits[:3]), ('filtered', [commits[3]]),
                        ('postfilter_dropped', [commits[4]])]:
        (cache / CACHE_FILES[key]).write_text(json.dumps(values))
    cfg['reports'] = {'outputs': ['csv', 'xlsx', 'ods'], 'top_n': 2}
    monkeypatch.setattr(st07_report, '_load_profile_rules_safe', lambda *_: {})
    monkeypatch.setattr(st07_report, '_copy_helper_scripts', lambda *_: [])
    monkeypatch.setattr(st07_report, '_dump_merged_config', lambda *_: None)
    st07_report.run(cfg, str(cache), str(out))
    baseline = {name: json.loads((out / (name + '_commits.json')).read_text())
                for name in ('relevant', 'filtered')}
    unchanged = {name: (out / name).read_bytes() for name in
                 ('profile_summary.json', 'profile_matrix.json', 'rule_trace.json',
                  'profile_summary.csv', 'profile_matrix.csv', 'rule_trace.csv')}
    cache_before = {p.relative_to(cache): p.read_bytes() for p in cache.rglob('*') if p.is_file()}
    protected = {p.relative_to(out): p.read_bytes() for p in out.rglob('*') if p.is_file()
                 and (p.relative_to(out).parts[0].startswith('ai_')
                      or p.relative_to(out).as_posix() == 'serve_ai.pyz')}
    item = copy.deepcopy(rows[0]['ai_analysis'])
    selected = (shas[0], shas[2], shas[3])
    schemas = {role: json.loads((out / 'ai_contract/schemas' / (role + '.json')).read_text())
               for role in ('analyst', 'cve', 'reviewer')}
    documents = {role: dict(run_id=source.analysis_id, role=role,
                           results={sha: {key: copy.deepcopy(item[key])
                                          for key in result_properties(schema)}
                                    for sha in selected}) for role, schema in schemas.items()}
    with running(out / 'serve_ai.pyz') as (port, log, errors):
        status, _, raw = request(port, prefix + '/result', method='POST', body=encode(documents))
        assert status == 200
        receipt = json.loads(raw)
        remote = {}
        for sha in selected:
            status, _, raw = request(port, prefix + '/result/' + sha)
            assert status == 200 and digest(raw) == receipt['results'][sha]
            remote[sha] = raw
        status, _, exported = request(port, prefix + '/export')
        assert status == 200
    bundle = tmp_path / 'returned.zip'
    bundle.write_bytes(exported)
    def no_prepare(*args, **kwargs):
        raise AssertionError('Report refresh must not rerun Stage 08')
    monkeypatch.setattr(st08_prepare_ai, 'run', no_prepare)
    original, calls = st07_report.run, []
    def real_report(*args, **kwargs):
        stats = original(*args, **kwargs)
        calls.append(stats)
        return stats
    monkeypatch.setattr(st07_report, 'run', real_report)
    assert import_results(cfg, bundle)['analyzed_commits'] == 3
    assert len(calls) == 1
    assert calls[0]['ai_analyzed_commits'] == 3 and calls[0]['ai_reported_commits'] == 2
    assert load_ai_results(out) == {sha: item for sha in selected}
    for sha in selected:
        assert (out / STORE_DIRECTORY / record_path(sha)).read_bytes() == remote[sha]
    details = {sha: value for path in (out / 'commits').rglob('*.json')
               for sha, value in json.loads(path.read_text()).items()}
    assert set(details) == {shas[0], shas[1], shas[3], shas[4]}
    for name, title, base, expected in [
            ('relevant', 'Relevant Commits', COMMIT_COLS, commits[:2]),
            ('filtered', 'Filtered Commits', COMMIT_COLS_FILTERED, commits[3:])]:
        data = json.loads((out / (name + '_commits.json')).read_text())
        assert [{k: v for k, v in row.items() if k != 'ai_analysis'} for row in data] == baseline[name]
        for row in data:
            assert details[row['commit']] == row
            if row['commit'] in selected:
                assert row['ai_analysis'] == item
            else:
                assert 'ai_analysis' not in row
        with (out / (name + '_commits.csv')).open(newline='', encoding='utf-8') as stream:
            table = list(csv.reader(stream))
        assert_summary(table[0], table[1:], base, expected)
        for stem in (name + '_commits', 'summary'):
            workbook = load_workbook(out / (stem + '.xlsx'), data_only=False)
            try:
                table = [list(row) for row in workbook[title].iter_rows(values_only=True)]
                assert_summary(table[0], table[1:], base, expected)
            finally:
                workbook.close()
            table = ods_tables(out / (stem + '.ods'))[title]
            assert_summary(table[0], table[1:], base, expected)
    assert cache_before == {p.relative_to(cache): p.read_bytes() for p in cache.rglob('*') if p.is_file()}
    assert all((out / name).read_bytes() == data for name, data in protected.items())
    assert all((out / name).read_bytes() == data for name, data in unchanged.items())
