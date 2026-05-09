"""Extra spreadsheet tests: write_summary_*, _matrix_rows, _stats_rows."""
import os
import pytest

from lib.spreadsheet import (
    _matrix_rows, _stats_rows,
    write_summary_ods, write_profile_summary_ods, write_profile_matrix_ods,
)

HAS_OPENPYXL = False
try:
    import openpyxl
    HAS_OPENPYXL = True
    from lib.spreadsheet import (
        write_summary_xlsx, write_profile_summary_xlsx, write_profile_matrix_xlsx,
    )
except ImportError:
    pass


def _commit(sha='abc', score=80, rank=1, profiles=None, profile_scores=None):
    profiles = profiles if profiles is not None else ['networking']
    return {
        'commit': sha, 'subject': f'fix: {sha}', 'score': score,
        '_rank': rank, 'author_name': 'Dev', 'author_time': 1700000000,
        'matched_profiles': profiles,
        'product_evidence': [],
        'scoring': {'profiles': profile_scores or {'networking': score}},
    }


def _profile_summary(profiles=None):
    return {
        'networking': {'count': 3, 'total_score': 180, 'top_score': 80},
        'security':   {'count': 1, 'total_score': 50,  'top_score': 50},
    }


# ── _matrix_rows ──────────────────────────────────────────────────────────────
def test_matrix_rows_single_profile():
    rows = _matrix_rows([_commit('a', profiles=['networking'])])
    assert len(rows) == 1
    assert rows[0][3] == 'networking'


def test_matrix_rows_multi_profile():
    c = _commit('b', profiles=['networking', 'security'],
                profile_scores={'networking': 40, 'security': 30})
    rows = _matrix_rows([c])
    assert len(rows) == 2
    profile_names = [r[3] for r in rows]
    assert 'networking' in profile_names
    assert 'security' in profile_names


def test_matrix_rows_empty():
    assert _matrix_rows([]) == []


def test_matrix_rows_no_matched_profiles():
    c = _commit('c', profiles=[])
    assert _matrix_rows([c]) == []


def test_matrix_rows_native_types():
    rows = _matrix_rows([_commit('d')], native_types=True)
    assert isinstance(rows[0][4], float)


# ── _stats_rows ───────────────────────────────────────────────────────────────
def test_stats_rows_mixed_types():
    stats = {'total': 100, 'ratio': 0.42, 'label': 'ok'}
    rows = _stats_rows(stats)
    keys = [r[0] for r in rows]
    assert 'total' in keys
    assert 'ratio' in keys
    assert 'label' in keys


def test_stats_rows_empty():
    assert _stats_rows({}) == []


def test_stats_rows_sorted():
    stats = {'z_key': 1, 'a_key': 2}
    rows = _stats_rows(stats)
    assert rows[0][0] == 'a_key'


# ── write_summary_ods ─────────────────────────────────────────────────────────
def test_write_summary_ods_created(tmp_path):
    p = str(tmp_path / 'summary.ods')
    write_summary_ods(p, [_commit()], [], _profile_summary(),
                      report_stats={'total': 1})
    assert os.path.exists(p)
    assert os.path.getsize(p) > 0


def test_write_summary_ods_with_filtered(tmp_path):
    p = str(tmp_path / 'summary_f.ods')
    flt = [_commit('f')]
    flt[0]['_filter_reason'] = 'path_blacklist'
    write_summary_ods(p, [_commit()], flt, _profile_summary())
    assert os.path.exists(p)


def test_write_summary_ods_empty_scored(tmp_path):
    p = str(tmp_path / 'empty.ods')
    write_summary_ods(p, [], [], {})
    assert os.path.exists(p)


def test_write_profile_summary_ods(tmp_path):
    p = str(tmp_path / 'ps.ods')
    write_profile_summary_ods(p, _profile_summary())
    assert os.path.exists(p)
    assert os.path.getsize(p) > 0


def test_write_profile_matrix_ods(tmp_path):
    p = str(tmp_path / 'pm.ods')
    write_profile_matrix_ods(p, [_commit()])
    assert os.path.exists(p)


# ── write_summary_xlsx ────────────────────────────────────────────────────────
@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not available')
def test_write_summary_xlsx_created(tmp_path):
    p = str(tmp_path / 'summary.xlsx')
    write_summary_xlsx(p, [_commit()], [], _profile_summary(),
                       report_stats={'total': 1})
    assert os.path.exists(p)
    assert os.path.getsize(p) > 0


@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not available')
def test_write_summary_xlsx_with_filtered(tmp_path):
    p = str(tmp_path / 'summary_f.xlsx')
    flt = [_commit('f')]
    flt[0]['_filter_reason'] = 'path_blacklist'
    write_summary_xlsx(p, [_commit()], flt, _profile_summary())
    assert os.path.exists(p)


@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not available')
def test_write_summary_xlsx_empty(tmp_path):
    p = str(tmp_path / 'empty.xlsx')
    write_summary_xlsx(p, [], [], {})
    assert os.path.exists(p)


@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not available')
def test_write_profile_summary_xlsx(tmp_path):
    p = str(tmp_path / 'ps.xlsx')
    write_profile_summary_xlsx(p, _profile_summary())
    assert os.path.exists(p)


@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not available')
def test_write_profile_matrix_xlsx(tmp_path):
    p = str(tmp_path / 'pm.xlsx')
    write_profile_matrix_xlsx(p, [_commit()])
    assert os.path.exists(p)


@pytest.mark.skipif(not HAS_OPENPYXL, reason='openpyxl not available')
def test_write_summary_xlsx_contains_rule_trace_sheet(tmp_path):
    p = str(tmp_path / 'summary_trace.xlsx')
    commit = _commit()
    commit['scoring'] = {
        'profiles': {'p': 42},
        'trace': {'profiles': {'p': {
            'final_score': 42,
            'rules': {'r1': {
                'matched': True,
                'matched_level': 'matched',
                'score': 42,
                'matches': {
                    'keywords_whitelist': [{'pattern': 'usb*', 'value': 'subject'}],
                    'path_whitelist': [],
                    'commit_whitelist': [],
                },
            }},
        }}},
    }
    write_summary_xlsx(p, [commit], [], _profile_summary())
    import zipfile
    with zipfile.ZipFile(p) as zf:
        workbook = zf.read('xl/workbook.xml').decode('utf-8')
    assert 'Rule Trace' in workbook
