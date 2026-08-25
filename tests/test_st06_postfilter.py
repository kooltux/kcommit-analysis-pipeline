"""Tests for lib.stages.st06_postfilter -- run(), _get_threshold, _score_buckets.

v13.0.0 (E.7):
  - Added tests for _score_buckets() helper.
  - Added tests asserting run() writes postfilter_debug.json with the expected
    summary structure (keys: summary, score_distribution).
  - Added test asserting CACHE_FILES['postfilter_debug'] key exists.

v18.0.1 (Fix 5): updated bucket-label assertions from '100+' to '>=100'.
  The score cap was removed in v16.5.0; the old label was misleading.
"""
import json
import os
from unittest.mock import patch

from lib.stages.st06_postfilter import run, _get_threshold, _score_buckets, _enrich_backport
from lib.manifest import CACHE_FILES


def _scored_commit(sha, score, rank=None):
    c = {'commit': sha, 'subject': 'fix: %s' % sha, 'score': score,
         'author_name': 'A', 'author_time': 0,
         'matched_profiles': [], 'product_evidence': []}
    if rank is not None:
        c['_rank'] = rank
    return c


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f)


def _read_json(path):
    with open(path) as f:
        return json.load(f)


# -- _get_threshold ------------------------------------------------------------
def test_get_threshold_default():
    assert _get_threshold({}) == 0.0

def test_get_threshold_from_filter():
    assert _get_threshold({'filter': {'min_score': 25}}) == 25.0

def test_get_threshold_ignores_reports():
    assert _get_threshold({'reports': {'min_score': 99}}) == 0.0

def test_get_threshold_bad_value_returns_zero():
    assert _get_threshold({'filter': {'min_score': 'high'}}) == 0.0


# -- _score_buckets ------------------------------------------------------------
def test_score_buckets_empty():
    b = _score_buckets([])
    assert b['0'] == 0
    assert b['>=100'] == 0  # Fix 5 (v18.0.1): was '100+'

def test_score_buckets_zero_score():
    b = _score_buckets([_scored_commit('x', 0)])
    assert b['0'] == 1
    assert sum(v for k, v in b.items() if k != '0') == 0

def test_score_buckets_hundred_plus():
    b = _score_buckets([_scored_commit('a', 100), _scored_commit('b', 200)])
    assert b['>=100'] == 2  # Fix 5 (v18.0.1): was '100+'

def test_score_buckets_various():
    commits = [
        _scored_commit('a', 0),
        _scored_commit('b', 5),
        _scored_commit('c', 15),
        _scored_commit('d', 25),
        _scored_commit('e', 40),
        _scored_commit('f', 60),
        _scored_commit('g', 80),
        _scored_commit('h', 150),
    ]
    b = _score_buckets(commits)
    assert b['0'] == 1
    assert b['1-9'] == 1
    assert b['10-19'] == 1
    assert b['20-29'] == 1
    assert b['30-49'] == 1
    assert b['50-74'] == 1
    assert b['75-99'] == 1
    assert b['>=100'] == 1  # Fix 5 (v18.0.1): was '100+'

def test_score_buckets_boundary_values():
    """Verify bucket boundary conditions (inclusive lower, exclusive upper)."""
    commits = [
        _scored_commit('a', 9),    # 1-9
        _scored_commit('b', 10),   # 10-19
        _scored_commit('c', 19),   # 10-19
        _scored_commit('d', 20),   # 20-29
        _scored_commit('e', 30),   # 30-49
        _scored_commit('f', 50),   # 50-74
        _scored_commit('g', 75),   # 75-99
        _scored_commit('h', 99),   # 75-99
        _scored_commit('i', 100),  # >=100
    ]
    b = _score_buckets(commits)
    assert b['1-9']   == 1
    assert b['10-19'] == 2
    assert b['20-29'] == 1
    assert b['30-49'] == 1
    assert b['50-74'] == 1
    assert b['75-99'] == 2
    assert b['>=100'] == 1  # Fix 5 (v18.0.1): was '100+'


# -- run(): rank assignment ----------------------------------------------------
def test_run_assigns_rank(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    commits = [_scored_commit('aaa', 50), _scored_commit('bbb', 80),
               _scored_commit('ccc', 30)]
    _write_json(os.path.join(cache, CACHE_FILES['scored']), commits)
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [])

    relevant, low, thresh = run({}, cache)
    assert [c['commit'] for c in relevant] == ['bbb', 'aaa', 'ccc']
    assert [c['_rank'] for c in relevant] == [1, 2, 3]
    assert thresh == 0.0
    assert low == []


# -- run(): threshold drops commits --------------------------------------------
def test_run_threshold_drops_low_scores(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    commits = [_scored_commit('high', 80), _scored_commit('low', 5)]
    _write_json(os.path.join(cache, CACHE_FILES['scored']), commits)
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [])

    cfg = {'filter': {'min_score': 10}}
    relevant, low, thresh = run(cfg, cache)
    assert len(relevant) == 1
    assert relevant[0]['commit'] == 'high'
    assert relevant[0]['_rank'] == 1
    assert len(low) == 1
    assert low[0]['commit'] == 'low'
    assert 'score_below_threshold' in low[0]['_filter_reason']


# -- run(): dropped written to postfilter cache --------------------------------
def test_run_writes_postfilter_dropped_cache(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']),
                [_scored_commit('keep', 50), _scored_commit('drop', 2)])
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [_scored_commit('pre', 1)])

    run({'filter': {'min_score': 10}}, cache)
    dropped = _read_json(os.path.join(cache, CACHE_FILES['postfilter_dropped']))
    shas = [c['commit'] for c in dropped]
    assert shas == ['drop']


# -- run(): relevant written to cache ------------------------------------------
def test_run_writes_relevant_cache(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']),
                [_scored_commit('abc', 40)])
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [])

    run({}, cache)
    relevant = _read_json(os.path.join(cache, CACHE_FILES['relevant']))
    assert len(relevant) == 1
    assert relevant[0]['commit'] == 'abc'
    assert relevant[0]['_rank'] == 1


# -- run(): empty scored list --------------------------------------------------
def test_run_empty_scored(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']), [])
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [])
    relevant, low, _ = run({}, cache)
    assert relevant == []
    assert low == []


# -- run(): zero-score commits kept when no threshold --------------------------
def test_run_zero_score_kept_without_threshold(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']),
                [_scored_commit('zero', 0)])
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [])
    relevant, low, _ = run({}, cache)
    assert len(relevant) == 1
    assert low == []


# == E.7: postfilter_debug.json written by run() ==============================

def test_run_writes_postfilter_debug_json(tmp_path):
    """E.7: run() must write postfilter_debug.json in the cache directory."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']),
                [_scored_commit('a', 80), _scored_commit('b', 5)])
    run({'filter': {'min_score': 10}}, cache)
    debug_path = os.path.join(cache, CACHE_FILES['postfilter_debug'])
    assert os.path.isfile(debug_path), 'postfilter_debug.json not written'


def test_postfilter_debug_json_top_level_keys(tmp_path):
    """E.7: postfilter_debug.json must have 'summary' and 'score_distribution' keys."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']),
                [_scored_commit('a', 80), _scored_commit('b', 5)])
    run({'filter': {'min_score': 10}}, cache)
    data = _read_json(os.path.join(cache, CACHE_FILES['postfilter_debug']))
    assert 'summary' in data
    assert 'score_distribution' in data


def test_postfilter_debug_json_summary_keys(tmp_path):
    """E.7: summary block must contain the documented keys."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']),
                [_scored_commit('a', 80), _scored_commit('b', 5)])
    run({'filter': {'min_score': 10}}, cache)
    data = _read_json(os.path.join(cache, CACHE_FILES['postfilter_debug']))
    s = data['summary']
    for key in ('total_scored', 'kept', 'dropped', 'threshold',
                'top_score', 'bottom_kept_score', 'top_dropped_score'):
        assert key in s, 'postfilter_debug summary missing key: %r' % (key,)


def test_postfilter_debug_json_summary_values(tmp_path):
    """E.7: summary counts must reflect the actual run."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']),
                [_scored_commit('a', 80), _scored_commit('b', 5)])
    run({'filter': {'min_score': 10}}, cache)
    data = _read_json(os.path.join(cache, CACHE_FILES['postfilter_debug']))
    s = data['summary']
    assert s['total_scored'] == 2
    assert s['kept']         == 1
    assert s['dropped']      == 1
    assert s['threshold']    == 10.0
    assert s['top_score']    == 80
    assert s['bottom_kept_score'] == 80
    assert s['top_dropped_score'] == 5


def test_postfilter_debug_json_score_distribution_keys(tmp_path):
    """E.7: score_distribution must have 'all_scored', 'kept', 'dropped' sub-dicts."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']),
                [_scored_commit('a', 80)])
    run({}, cache)
    data = _read_json(os.path.join(cache, CACHE_FILES['postfilter_debug']))
    sd = data['score_distribution']
    assert 'all_scored' in sd
    assert 'kept' in sd
    assert 'dropped' in sd


def test_postfilter_debug_json_no_threshold_empty_dropped_buckets(tmp_path):
    """E.7: when no threshold is set, dropped score_distribution bucket should
    be all zeros."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']),
                [_scored_commit('a', 80)])
    run({}, cache)
    data = _read_json(os.path.join(cache, CACHE_FILES['postfilter_debug']))
    dropped_buckets = data['score_distribution']['dropped']
    assert all(v == 0 for v in dropped_buckets.values())


def test_postfilter_debug_json_empty_scored(tmp_path):
    """E.7: run() on empty input must still write valid postfilter_debug.json."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']), [])
    run({}, cache)
    data = _read_json(os.path.join(cache, CACHE_FILES['postfilter_debug']))
    assert data['summary']['total_scored'] == 0
    assert data['summary']['kept']         == 0
    assert data['summary']['dropped']      == 0
    assert data['summary']['top_score']    == 0


# == backport enrichment (v18.4.0) ============================================

def _cfg_kernel(count_hunks=False):
    cfg = {'kernel': {'source_dir': '/repo', 'rev_old': 'v1', 'rev_new': 'v2'}}
    if count_hunks:
        cfg['collect'] = {'count_hunks': True}
    return cfg


def test_run_attaches_backport_indicators(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    c = _scored_commit('abc', 40)
    c['stats'] = {'files_changed': 2, 'lines_changed': 30, 'hunks': 0}
    c['files'] = ['drivers/usb/core.c', 'drivers/usb/hub.c']
    c['meta'] = {}
    _write_json(os.path.join(cache, CACHE_FILES['scored']), [c])
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [])
    relevant, _, _ = run(_cfg_kernel(), cache)
    r = relevant[0]
    assert 'backport_complexity' in r
    assert 'pick_priority' in r
    # single relevant commit → it is the run max → relevance normalized to 100
    assert 0 <= r['pick_priority'] <= 100


def test_enrich_backport_counts_hunks_when_enabled():
    relevant = [
        {'commit': 'a' * 40, 'score': 50, 'files': ['x.c'], 'meta': {},
         'stats': {'files_changed': 1, 'lines_changed': 10}},
    ]
    fake_counts = {'a' * 40: 5}
    with patch('lib.stages.st06_postfilter.batch_count_hunks',
               return_value=fake_counts) as m:
        _enrich_backport(_cfg_kernel(count_hunks=True), relevant)
    m.assert_called_once()
    assert relevant[0]['stats']['hunks'] == 5


def test_enrich_backport_skips_hunks_when_disabled():
    relevant = [
        {'commit': 'a' * 40, 'score': 50, 'files': ['x.c'], 'meta': {},
         'stats': {'files_changed': 1, 'lines_changed': 10}},
    ]
    with patch('lib.stages.st06_postfilter.batch_count_hunks') as m:
        _enrich_backport(_cfg_kernel(count_hunks=False), relevant)
    m.assert_not_called()
    assert relevant[0]['stats'].get('hunks', 0) == 0


def test_enrich_backport_hunk_failure_is_tolerated():
    relevant = [
        {'commit': 'a' * 40, 'score': 50, 'files': ['x.c'], 'meta': {},
         'stats': {'files_changed': 1, 'lines_changed': 10}},
    ]
    with patch('lib.stages.st06_postfilter.batch_count_hunks',
               side_effect=RuntimeError('git boom')):
        _enrich_backport(_cfg_kernel(count_hunks=True), relevant)
    # hunks defaults to 0, enrichment still ran
    assert relevant[0]['stats']['hunks'] == 0
    assert 'backport_complexity' in relevant[0]


def test_enrich_backport_empty_list():
    assert _enrich_backport(_cfg_kernel(), []) == []


def test_run_attaches_score_norm(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    # two commits: top score 100 → norm 100; other 25 → norm 25
    a = _scored_commit('a', 100); a['files'] = ['x.c']; a['meta'] = {}
    b = _scored_commit('b', 25);  b['files'] = ['y.c']; b['meta'] = {}
    _write_json(os.path.join(cache, CACHE_FILES['scored']), [a, b])
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [])
    relevant, _, _ = run(_cfg_kernel(), cache)
    by_sha = {c['commit']: c for c in relevant}
    assert by_sha['a']['score_norm'] == 100
    assert by_sha['b']['score_norm'] == 25


def test_enrich_backport_score_norm_zero_max_safe():
    relevant = [{'commit': 'a' * 40, 'score': 0, 'files': ['x.c'], 'meta': {},
                 'stats': {'files_changed': 1, 'lines_changed': 1}}]
    _enrich_backport(_cfg_kernel(), relevant)
    assert relevant[0]['score_norm'] == 0


# == CACHE_FILES manifest key ==================================================

def test_cache_files_has_postfilter_debug_key():
    """E.7: CACHE_FILES must expose 'postfilter_debug' so callers have a
    stable, named key to reference rather than a hardcoded filename."""
    assert 'postfilter_debug' in CACHE_FILES
    assert CACHE_FILES['postfilter_debug'].endswith('.json')
