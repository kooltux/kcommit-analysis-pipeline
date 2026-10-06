"""Stage 07 must list every spreadsheet file it writes in generated_files (v19.11.1).

Regression guard: relevant_commits.ods was dropped from
report_stats['generated_files'] in v19.10.0, and the profile summary/matrix
spreadsheets were never listed.  The spreadsheet writers are faked so the
test does not depend on openpyxl or odfpy rendering.
"""
import json
import os

import pytest

import lib.spreadsheet as spreadsheet
from lib.manifest import CACHE_FILES
from lib.stages import st07_report

WRITERS = [
    'write_xlsx', 'write_ods',
    'write_profile_summary_xlsx', 'write_profile_matrix_xlsx',
    'write_profile_summary_ods', 'write_profile_matrix_ods',
    'write_summary_xlsx', 'write_summary_ods',
]


@pytest.fixture
def fake_writers(monkeypatch):
    def _fake(path, *args, **kwargs):
        with open(path, 'wb') as fh:
            fh.write(b'x')
    for name in WRITERS:
        monkeypatch.setattr(spreadsheet, name, _fake)


def _run(tmp_path, outputs, with_filtered=True):
    cache = tmp_path / 'cache'
    out = tmp_path / 'output'
    cache.mkdir()
    if with_filtered:
        dropped = [{'commit': 'a' * 40, 'subject': 'dropped', '_filter_reason': 'test'}]
        (cache / CACHE_FILES['filtered']).write_text(json.dumps(dropped), encoding='utf-8')
    cfg = {'reports': {'outputs': outputs}, 'paths': {'assets_dir': str(tmp_path / 'assets')}}
    stats = st07_report.run(cfg, str(cache), str(out))
    return stats, out


def _expected(ext):
    return {name + '.' + ext for name in (
        'relevant_commits', 'filtered_commits', 'profile_summary',
        'profile_matrix', 'summary')}


@pytest.mark.parametrize('ext', ['xlsx', 'ods'])
def test_every_spreadsheet_file_is_listed(tmp_path, fake_writers, ext):
    stats, out = _run(tmp_path, [ext])
    listed = set(stats['generated_files'])
    assert _expected(ext) <= listed
    for name in _expected(ext):
        assert (out / name).is_file()


@pytest.mark.parametrize('ext,other', [('xlsx', 'ods'), ('ods', 'xlsx')])
def test_unrequested_spreadsheet_format_is_not_listed(tmp_path, fake_writers, ext, other):
    stats, out = _run(tmp_path, [ext])
    assert not any(f.endswith('.' + other) for f in stats['generated_files'])


def test_both_formats_listed_together(tmp_path, fake_writers):
    stats, _ = _run(tmp_path, ['xlsx', 'ods'])
    assert (_expected('xlsx') | _expected('ods')) <= set(stats['generated_files'])


def test_filtered_spreadsheets_only_listed_when_there_are_filtered_commits(tmp_path, fake_writers):
    stats, _ = _run(tmp_path, ['xlsx', 'ods'], with_filtered=False)
    listed = set(stats['generated_files'])
    assert 'filtered_commits.xlsx' not in listed
    assert 'filtered_commits.ods' not in listed
    assert 'relevant_commits.ods' in listed


def test_generated_files_are_relative_existing_and_sorted(tmp_path, fake_writers):
    stats, out = _run(tmp_path, ['xlsx', 'ods'])
    files = stats['generated_files']
    assert files == sorted(set(files))
    assert not any(os.path.isabs(f) for f in files)
    for rel in files:
        assert (out / rel).exists(), rel
