"""Inspect emitted advisory summary cells in CSV and standalone/combined workbooks."""
import copy
import csv
import json
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

import pytest

from lib.ai_contract import validate_assessment
from lib.ai_report import AI_SUMMARY_COLUMNS, ai_columns, ai_summary_cells
from lib.manifest import CACHE_FILES, COMMIT_COLS, COMMIT_COLS_FILTERED
from lib import spreadsheet
from lib.stages import st07_report
from test_ai_import_sources import record


@pytest.fixture
def rows():
    schema = json.loads((Path(__file__).resolve().parents[1] /
                         'configs/ai/schemas/result.json').read_text())
    assessment = record(SimpleNamespace(schema=schema))
    assessment.update(ai_summary='=1+1', ai_is_bug_fix=True, rv_agreement='disagree',
        rv_notes=['ai_backport_recommendation: [strong] - "strong_yes" -> "no" (cost)'],
        rv_recommendation=['ai_backport_recommendation: use "no"'])
    validate_assessment('a' * 40, assessment, schema)
    values = [dict(commit=letter * 40, subject='Fix', score=11-i, pick_priority=30-i,
                   _rank=i+1, _filter_reason='score') for i, letter in enumerate('abcd')]
    for i in (0, 2):
        values[i]['ai_analysis'] = copy.deepcopy(assessment)
    return values


def assert_summary(header, rows, base_columns, expected):
    n = len(base_columns)
    assert header[:n] == list(base_columns)
    assert header[n:] == list(AI_SUMMARY_COLUMNS)
    assert rows[0][n:] == ['Yes', 'No', 'Yes', 'critical', 'very_easy',
                           'strong_yes', "'=1+1", 'disagree']
    assert all(value in ('', None) for value in rows[1][n:])
    assert len(rows[0]) == len(rows[1]) == len(header)
    for row, source in zip(rows, expected):
        assert int(row[0]) == source['_rank'] and row[1] == source['commit'][:12]
        assert float(row[5]) == source['pick_priority'] and float(row[12]) == source['score']


def ods_tables(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read('content.xml'))
    tables = {}
    for table in root.iter():
        if table.tag.endswith('}table'):
            name = next(v for k, v in table.attrib.items() if k.endswith('}name'))
            tables[name] = [[ ''.join(cell.itertext()) for cell in row
                              if cell.tag.endswith('}table-cell')]
                            for row in table if row.tag.endswith('}table-row')]
    return tables


@pytest.mark.parametrize('kind', ['xlsx', 'ods'])
@pytest.mark.parametrize('combined', [False, True])
def test_real_workbooks_include_identical_ai_summaries(tmp_path, rows, kind, combined):
    before = copy.deepcopy(rows)
    path = tmp_path / ('report.' + kind)
    if combined:
        getattr(spreadsheet, 'write_summary_' + kind)(str(path), rows[:2], rows[2:], {})
    else:
        getattr(spreadsheet, 'write_' + kind)(str(path), rows[:2], {}, sheet_name='Relevant Commits')
    if kind == 'xlsx':
        from openpyxl import load_workbook
        workbook = load_workbook(path, data_only=False)
        tables = {sheet.title: [list(row) for row in sheet.iter_rows(values_only=True)]
                  for sheet in workbook.worksheets}
        assert workbook['Relevant Commits'].cell(2, len(COMMIT_COLS) + 7).data_type == 's'
        workbook.close()
    else:
        tables = ods_tables(path)
    for name, base in [('Relevant Commits', COMMIT_COLS), ('Filtered Commits', COMMIT_COLS_FILTERED)]:
        if name == 'Filtered Commits' and not combined:
            continue
        expected = rows[:2] if name == 'Relevant Commits' else rows[2:]
        assert_summary(tables[name][0], tables[name][1:], base, expected)
    assert rows == before


def test_real_stage_csv_preserves_scope_scores_and_missing_findings(tmp_path, monkeypatch, rows):
    cache, output = tmp_path / 'cache', tmp_path / 'output'
    cache.mkdir()
    for key, values in [('relevant', rows[:2]), ('filtered', rows[2:]), ('postfilter_dropped', [])]:
        plain = [{k: v for k, v in row.items() if k != 'ai_analysis'} for row in values]
        (cache / CACHE_FILES[key]).write_text(json.dumps(plain))
    results = {row['commit']: row['ai_analysis'] for row in rows if 'ai_analysis' in row}
    before = {p.name: p.read_bytes() for p in cache.iterdir()}
    monkeypatch.setattr(st07_report, '_load_profile_rules_safe', lambda *_: {})
    monkeypatch.setattr(st07_report, '_copy_helper_scripts', lambda *_: [])
    monkeypatch.setattr(st07_report, '_dump_merged_config', lambda *_: None)
    cfg = {'reports': {'outputs': ['csv'], 'top_n': 0}, 'paths': {'templates_dir': None}}
    st07_report.run(cfg, str(cache), str(output), results)
    for name, base in [('relevant', COMMIT_COLS), ('filtered', COMMIT_COLS_FILTERED)]:
        with (output / (name + '_commits.csv')).open(newline='') as stream:
            data = list(csv.reader(stream))
        assert_summary(data[0], data[1:], base, rows[:2] if name == 'relevant' else rows[2:])
    assert before == {p.name: p.read_bytes() for p in cache.iterdir()}
    exported = json.loads((output / 'relevant_commits.json').read_text())
    assert exported[0]['ai_analysis']['ai_summary'] == '=1+1'
    assert exported[0]['ai_analysis']['ai_backport_recommendation'] == 'strong_yes'
    assert 'ai_analysis' not in exported[1]


def test_empty_ai_keeps_original_headers_and_rows(rows):
    plain = [{k: v for k, v in row.items() if k != 'ai_analysis'} for row in rows]
    assert ai_columns(COMMIT_COLS, plain) == list(COMMIT_COLS)
    assert len(st07_report._commit_rows(plain)[0]) == len(COMMIT_COLS)
    columns, body = spreadsheet._commit_table(plain)
    assert columns == list(COMMIT_COLS)
    assert all(len(row) == len(columns) for row in body)
    assert body == [spreadsheet._commit_row(row, native_types=True) for row in plain]
    assert ai_summary_cells(plain[0]) == [''] * len(AI_SUMMARY_COLUMNS)
