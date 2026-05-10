"""Tests for lib.spreadsheet — write_xlsx, write_ods round-trips."""
import os
import pytest

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from lib.spreadsheet import (
    write_xlsx, write_ods,
    write_profile_summary_xlsx, write_profile_matrix_xlsx,
    write_profile_summary_ods,  write_profile_matrix_ods,
)


def _scored():
    return [{
        'commit': 'abc123def456', 'subject': 'usb: fix hub reset',
        'score': 80, '_rank': 1, 'author_name': 'Dev', 'author_time': 1700000000,
        'matched_profiles': ['security_fixes'], 'product_evidence': ['config_map:CONFIG_USB'],
    }]


def _filtered():
    return [{
        'commit': 'dead0000beef', 'subject': 'docs: typo fix',
        'score': 0, 'author_name': 'Dev', 'author_time': 1700000000,
        'matched_profiles': [], 'product_evidence': [],
        '_filter_reason': 'path_blacklist',
    }]


def _profile_summary():
    return {
        'security_fixes': {'commit_count': 1, 'total_score': 80,
                     'avg_score': 80.0, 'description': ''},
    }


# ── XLSX ───────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not installed')
def test_write_xlsx_creates_file(tmp_path):
    path = str(tmp_path / 'out.xlsx')
    write_xlsx(path, _scored(), _profile_summary())
    assert os.path.exists(path)
    assert os.path.getsize(path) > 0


@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not installed')
def test_write_xlsx_correct_row_count(tmp_path):
    path = str(tmp_path / 'out.xlsx')
    write_xlsx(path, _scored(), _profile_summary())
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    # 1 header row + 1 data row = 2 rows min
    assert ws.max_row >= 2


@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not installed')
def test_write_xlsx_filtered_include_reason(tmp_path):
    path = str(tmp_path / 'filtered.xlsx')
    write_xlsx(path, _filtered(), {}, include_reason=True)
    assert os.path.exists(path)


@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not installed')
def test_write_profile_summary_xlsx(tmp_path):
    path = str(tmp_path / 'ps.xlsx')
    write_profile_summary_xlsx(path, _profile_summary())
    assert os.path.exists(path)


@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not installed')
def test_write_profile_matrix_xlsx(tmp_path):
    path = str(tmp_path / 'pm.xlsx')
    write_profile_matrix_xlsx(path, _scored())
    assert os.path.exists(path)


@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not installed')
def test_write_xlsx_empty_scored(tmp_path):
    path = str(tmp_path / 'empty.xlsx')
    write_xlsx(path, [], {})
    assert os.path.exists(path)


# ── ODS ────────────────────────────────────────────────────────────────────
def test_write_ods_creates_file(tmp_path):
    path = str(tmp_path / 'out.ods')
    write_ods(path, _scored(), _profile_summary())
    assert os.path.exists(path)
    assert os.path.getsize(path) > 0


def test_write_ods_filtered_include_reason(tmp_path):
    path = str(tmp_path / 'filtered.ods')
    write_ods(path, _filtered(), {}, include_reason=True)
    assert os.path.exists(path)


def test_write_profile_summary_ods(tmp_path):
    path = str(tmp_path / 'ps.ods')
    write_profile_summary_ods(path, _profile_summary())
    assert os.path.exists(path)


def test_write_profile_matrix_ods(tmp_path):
    path = str(tmp_path / 'pm.ods')
    write_profile_matrix_ods(path, _scored())
    assert os.path.exists(path)


def test_write_ods_empty_scored(tmp_path):
    path = str(tmp_path / 'empty.ods')
    write_ods(path, [], {})
    assert os.path.exists(path)


def test_commit_row_contains_profile_scores_text():
    from lib.spreadsheet import _commit_row
    row = _commit_row({
        'commit': 'b'*40, 'subject': 'x', 'author_name': 'A', 'author_time': 1710000000,
        'score': 7, 'matched_profiles': ['p1'], 'product_evidence': ['e1'],
        'scoring': {'profiles': {'p2': 3, 'p1': 7}}
    })
    assert row[0] == ''          # _rank not set → empty string
    assert row[7] == 'p1:7; p2:3'
