"""Extra spreadsheet tests: write_summary_*, _matrix_rows, _stats_rows."""
import os
import pytest

from lib.spreadsheet import (
    _matrix_rows, _stats_rows, _SECTION,
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
        'networking':     {'count': 3, 'total_score': 180, 'top_score': 80},
        'security_fixes': {'count': 1, 'total_score': 50,  'top_score': 50},
    }


# ── _matrix_rows ──────────────────────────────────────────────────────────────
def test_matrix_rows_single_profile():
    rows = _matrix_rows([_commit('a', profiles=['networking'])])
    assert len(rows) == 1
    assert rows[0][3] == 'networking'


def test_matrix_rows_multi_profile():
    c = _commit('b', profiles=['networking', 'security_fixes'],
                profile_scores={'networking': 40, 'security_fixes': 30})
    rows = _matrix_rows([c])
    assert len(rows) == 2
    profile_names = [r[3] for r in rows]
    assert 'networking' in profile_names
    assert 'security_fixes' in profile_names


def test_matrix_rows_empty():
    assert _matrix_rows([]) == []


def test_matrix_rows_no_matched_profiles():
    c = _commit('c', profiles=[])
    assert _matrix_rows([c]) == []


def test_matrix_rows_native_types():
    rows = _matrix_rows([_commit('d')], native_types=True)
    assert isinstance(rows[0][4], float)


# ── _stats_rows (v18.3.0 structured output) ──────────────────────────────────

def _data_rows(rows):
    """Filter out _SECTION sentinel rows; return only (metric, value) data rows."""
    return [(m, v) for m, v in rows if m is not _SECTION]


def _section_titles(rows):
    """Return the list of section header titles in order."""
    return [v for m, v in rows if m is _SECTION]


def test_stats_rows_structure_has_sections():
    """_stats_rows always emits section headers even for empty input."""
    rows = _stats_rows({})
    sections = _section_titles(rows)
    assert 'Run Context'          in sections
    assert 'Analysis Parameters' in sections
    assert 'Pipeline Funnel'     in sections
    assert 'Scoring Summary'     in sections
    assert 'Coverage'            in sections


def test_stats_rows_empty_produces_only_sections():
    """With no populated fields, only section sentinel rows are present."""
    rows = _stats_rows({})
    data = _data_rows(rows)
    assert data == []


def test_stats_rows_funnel_fallback_from_report_stats():
    """Funnel data surfaced from flat report_stats keys when run_stats=None."""
    rs = {
        'st01_collected':          500,
        'st04_prefilter_kept':     400,
        'st04_prefilter_dropped':  100,
        'st05_total_scored':       400,
        'st06_postfilter_dropped':  20,
        'total_scored_commits':    380,
    }
    rows = _stats_rows(rs)
    data = dict(_data_rows(rows))
    assert data['Commits collected'] == 500
    assert data['After prefilter']   == 400
    assert data['In final report']   == 380


def test_stats_rows_run_stats_funnel_preferred():
    """run_stats funnel dict takes precedence over flat report_stats keys."""
    rs  = {'st01_collected': 999}   # should be ignored
    rns = {
        'funnel': {
            'collected':           200,
            'prefilter_kept':      180,
            'prefilter_dropped':    20,
            'scored':              180,
            'postfilter_kept':     170,
            'postfilter_dropped':   10,
            'final_report':        170,
            'pass_rate_pct':        85,
        }
    }
    rows = _stats_rows(rs, run_stats=rns)
    data = dict(_data_rows(rows))
    assert data['Commits collected']       == 200
    assert data['After postfilter (kept)'] == 170
    assert data['Overall pass rate']       == '85%'
    assert 'st01_collected' not in data


def test_stats_rows_scoring_summary_from_run_stats():
    """Scoring summary fields come from run_stats stage_05_scoring."""
    rns = {
        'stage_05_scoring': {
            'score_max':              95,
            'score_min':               5,
            'score_avg':             42.3,
            'score_median':          40.0,
            'zero_score_commits':     12,
            'multi_profile_commits':   7,
        }
    }
    rows = _stats_rows({}, run_stats=rns)
    data = dict(_data_rows(rows))
    assert data['Score max']             == 95
    assert data['Score min']             == 5
    assert data['Zero-score commits']    == 12
    assert data['Multi-profile commits'] == 7


def test_stats_rows_coverage_fields():
    """Coverage metrics are emitted from report_stats and run_stats."""
    rs  = {
        'commits_matched_zero_profiles': 3,
        'commits_with_product_evidence': 8,
    }
    rns = {
        'product_map_summary': {
            'kconfig_symbols_enabled': 1200,
            'compiled_files':           800,
            'compiled_dirs':             50,
        }
    }
    rows = _stats_rows(rs, run_stats=rns)
    data = dict(_data_rows(rows))
    assert data['Commits with no profile match'] == 3
    assert data['Commits with product evidence'] == 8
    assert data['KConfig symbols enabled']       == 1200
    assert data['Compiled files tracked']        ==  800


def test_stats_rows_section_order():
    """Section headers appear in the canonical order."""
    rows   = _stats_rows({})
    titles = _section_titles(rows)
    assert titles == ['Run Context', 'Analysis Parameters',
                      'Pipeline Funnel', 'Scoring Summary', 'Coverage']


def test_stats_rows_none_values_suppressed():
    """Fields whose value is None or empty string are not emitted."""
    rows = _stats_rows({'evaluation': {'git_source': None, 'git_range': None}})
    data = dict(_data_rows(rows))
    assert 'Git source' not in data
    assert 'Git range'  not in data


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
