"""Extra tests for lib.stages.st07_report — XLSX/ODS output, _fmt_date,
_profile_summary, _commit_rows."""
import csv, json, os
import pytest

from lib.stages.st07_report import run, _fmt_date, _commit_rows
from lib.manifest import CACHE_FILES


def _commit(sha='abc', score=50, rank=1, profiles=None):
    return {
        'commit': sha, 'subject': f'fix: {sha}', 'score': score,
        '_rank': rank, 'author_name': 'Dev', 'author_time': 1700000000,
        'matched_profiles': profiles or ['security'],
        'product_evidence': ['config_map:CONFIG_USB'],
    }


def _compiled_rules():
    return {
        'schema_hash': 'test',
        'rules': {},
        'profiles': {
            'security': {'description': 'Security', 'rules': {},
                         'merged': {'keywords_whitelist': [],
                                     'keywords_blacklist': [],
                                     'path_whitelist': [],
                                     'path_blacklist': [],
                                     'commit_whitelist': [],
                                     'commit_blacklist': []}},
        }
    }


def _setup(tmp_path, scored=None, filtered=None, outputs=None):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    scored   = scored   if scored   is not None else [_commit()]
    filtered = filtered if filtered is not None else []
    with open(os.path.join(cache, CACHE_FILES['relevant']), 'w') as f:
        json.dump(scored, f)
    with open(os.path.join(cache, CACHE_FILES['filtered']), 'w') as f:
        json.dump(filtered, f)
    with open(os.path.join(cache, CACHE_FILES['compiled_rules']), 'w') as f:
        json.dump(_compiled_rules(), f)
    cfg = {
        'reports': {'outputs': outputs or ['csv'], 'title': 'Test', 'top_n': 0},
        'paths':   {'templates_dir': None, 'cache_dir': cache,
                    'work_dir': str(tmp_path)},
        'profiles': {'active': {'security': 100}},
    }
    return cache, outdir, cfg


# ── _fmt_date ─────────────────────────────────────────────────────────────────
def test_fmt_date_unix_timestamp():
    result = _fmt_date(1700000000)
    assert '-' in result and ':' in result


def test_fmt_date_zero():
    # 0 is falsy in Python; _fmt_date guards with `if not ts: return ''`
    assert _fmt_date(0) == ''

def test_fmt_date_valid_unix():
    result = _fmt_date(1700000000)
    assert '-' in result and ':' in result  # YYYY-MM-DD HH:MM


def test_fmt_date_none():
    assert _fmt_date(None) == ''


def test_fmt_date_empty_string():
    assert _fmt_date('') == ''


def test_fmt_date_iso_string_fallback():
    """Non-integer ISO-like strings fall back to truncation."""
    result = _fmt_date('2024-05-01T12:34:56')
    assert result.startswith('2024-05-01T')


# ── _commit_rows ──────────────────────────────────────────────────────────────
def test_commit_rows_basic():
    rows = _commit_rows([_commit('abc', score=80, rank=1)])
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == 1        # rank
    assert 'abc' in row[1]   # sha (truncated to 12)
    assert row[5] == 80       # score


def test_commit_rows_include_reason():
    c = _commit('xyz')
    c['_filter_reason'] = 'path_blacklist'
    rows = _commit_rows([c], include_reason=True)
    assert rows[0][-1] == 'path_blacklist'


def test_commit_rows_empty():
    assert _commit_rows([]) == []


# ── XLSX output ───────────────────────────────────────────────────────────────
def test_xlsx_output_written(tmp_path):
    pytest.importorskip('openpyxl')
    cache, outdir, cfg = _setup(tmp_path, outputs=['xlsx'])
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'relevant_commits.xlsx'))


def test_xlsx_summary_written(tmp_path):
    pytest.importorskip('openpyxl')
    cache, outdir, cfg = _setup(tmp_path, outputs=['xlsx'])
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'summary.xlsx'))


def test_xlsx_filtered_written(tmp_path):
    pytest.importorskip('openpyxl')
    flt = [_commit('d')]
    flt[0]['_filter_reason'] = 'path_blacklist'
    cache, outdir, cfg = _setup(tmp_path, filtered=flt, outputs=['xlsx'])
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'filtered_commits.xlsx'))


# ── ODS output ────────────────────────────────────────────────────────────────
def test_ods_output_written(tmp_path):
    cache, outdir, cfg = _setup(tmp_path, outputs=['ods'])
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'relevant_commits.ods'))


def test_ods_summary_written(tmp_path):
    cache, outdir, cfg = _setup(tmp_path, outputs=['ods'])
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'summary.ods'))
