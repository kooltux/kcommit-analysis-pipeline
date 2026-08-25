"""Tests for lib.backport — backport_complexity, pick_priority."""
from lib.backport import (
    compute_backport_complexity,
    compute_pick_priority,
    normalize_score,
    enrich_commit_backport,
    _distinct_top_dirs,
)


# ── normalize_score ──────────────────────────────────────────────────────────
def test_normalize_score_basic():
    assert normalize_score(50, 100) == 50
    assert normalize_score(100, 100) == 100
    assert normalize_score(30, 200) == 15   # 100*30/200 = 15.0


def test_normalize_score_top_is_100():
    assert normalize_score(187, 187) == 100


def test_normalize_score_zero_max_is_safe():
    # max_score 0 clamps to 1 → no ZeroDivision; a 0 score stays 0
    assert normalize_score(0, 0) == 0


def test_normalize_score_clamps_to_100():
    assert normalize_score(300, 100) == 100


# ── _distinct_top_dirs ───────────────────────────────────────────────────────
def test_distinct_top_dirs_counts_subsystems():
    files = ['drivers/usb/core.c', 'drivers/net/x.c', 'include/linux/y.h']
    # top dirs: drivers, drivers, include → 2 distinct
    assert _distinct_top_dirs(files) == 2


def test_distinct_top_dirs_root_files_bucketed():
    assert _distinct_top_dirs(['Makefile', 'Kconfig']) == 1  # both root ('')


def test_distinct_top_dirs_empty():
    assert _distinct_top_dirs([]) == 0


# ── compute_backport_complexity ──────────────────────────────────────────────
def test_complexity_trivial_commit_is_low():
    c = {'stats': {'files_changed': 1, 'lines_changed': 3, 'hunks': 1},
         'files': ['drivers/usb/core.c'], 'meta': {}}
    r = compute_backport_complexity(c)
    assert r['complexity'] < 25


def test_complexity_large_scattered_commit_is_high():
    c = {'stats': {'files_changed': 80, 'lines_changed': 5000, 'hunks': 120},
         'files': ['drivers/a/x.c', 'net/b/y.c', 'fs/c/z.c', 'arch/arm/d.c'],
         'meta': {}}
    r = compute_backport_complexity(c)
    assert r['complexity'] >= 60


def test_complexity_stable_fix_gets_friendliness_reduction():
    base = {'stats': {'files_changed': 5, 'lines_changed': 120, 'hunks': 8},
            'files': ['drivers/usb/core.c', 'drivers/usb/hub.c'], 'meta': {}}
    plain = compute_backport_complexity(base)['complexity']
    friendly = dict(base)
    friendly['meta'] = {'has_stable_cc': True, 'is_fix': True}
    reduced = compute_backport_complexity(friendly)['complexity']
    assert reduced < plain
    # 15 (stable) + 10 (fix) = 25 reduction (capped at 25)
    assert plain - reduced == min(25, plain)


def test_complexity_merge_forced_to_100():
    c = {'stats': {'files_changed': 1, 'lines_changed': 1, 'hunks': 1},
         'files': ['x.c'], 'meta': {}, 'parents': ['a' * 40, 'b' * 40]}
    r = compute_backport_complexity(c)
    assert r['complexity'] == 100
    assert r['factors']['is_merge'] is True


def test_complexity_factors_exposed():
    c = {'stats': {'files_changed': 3, 'lines_changed': 40, 'hunks': 4},
         'files': ['drivers/a.c'], 'meta': {}}
    f = compute_backport_complexity(c)['factors']
    for key in ('files_pts', 'lines_pts', 'hunks_pts', 'spread_pts',
                'risk_raw', 'friendly', 'is_merge', 'distinct_top_dirs'):
        assert key in f


def test_complexity_no_hunks_term_when_hunks_absent():
    """When hunks==0 (counting disabled), the hunks term contributes nothing."""
    with_hunks = compute_backport_complexity(
        {'stats': {'files_changed': 2, 'lines_changed': 50, 'hunks': 40},
         'files': ['a/x.c'], 'meta': {}})
    without = compute_backport_complexity(
        {'stats': {'files_changed': 2, 'lines_changed': 50, 'hunks': 0},
         'files': ['a/x.c'], 'meta': {}})
    assert with_hunks['complexity'] > without['complexity']
    assert without['factors']['hunks_pts'] == 0


# ── compute_pick_priority ────────────────────────────────────────────────────
def test_pick_priority_high_score_low_complexity_is_high():
    # top score in run (score_norm=100), trivial to backport
    p = compute_pick_priority(score_norm=100, complexity=0)
    assert p == 100


def test_pick_priority_high_score_hard_backport_mid():
    # 0.70*100 + 0.30*(100-100) = 70
    p = compute_pick_priority(score_norm=100, complexity=100)
    assert p == 70


def test_pick_priority_low_score_easy_stays_low():
    # 0.70*0 + 0.30*100 = 30
    p = compute_pick_priority(score_norm=0, complexity=0)
    assert p == 30


def test_pick_priority_clamps_inputs():
    # out-of-range inputs are clamped into 0..100
    assert 0 <= compute_pick_priority(score_norm=999, complexity=-50) <= 100


# ── enrich_commit_backport ───────────────────────────────────────────────────
def test_enrich_attaches_all_fields():
    c = {'score': 50, 'stats': {'files_changed': 2, 'lines_changed': 20, 'hunks': 3},
         'files': ['drivers/a.c'], 'meta': {}}
    enrich_commit_backport(c, max_score=100)
    assert isinstance(c['backport_complexity'], int)
    assert isinstance(c['pick_priority'], int)
    assert c['score_norm'] == 50   # 100*50/100
    assert c['backport']['complexity'] == c['backport_complexity']
    assert 'factors' in c['backport']


def test_enrich_pick_priority_uses_score_norm():
    # pick_priority must equal 0.70*score_norm + 0.30*(100-complexity)
    c = {'score': 100, 'stats': {'files_changed': 1, 'lines_changed': 1, 'hunks': 1},
         'files': ['a.c'], 'meta': {}}
    enrich_commit_backport(c, max_score=100)
    expected = round(0.70 * c['score_norm'] + 0.30 * (100 - c['backport_complexity']))
    assert c['pick_priority'] == expected


def test_enrich_does_not_touch_score():
    c = {'score': 42, 'stats': {'files_changed': 1, 'lines_changed': 1, 'hunks': 1},
         'files': ['a.c'], 'meta': {}}
    enrich_commit_backport(c, max_score=42)
    assert c['score'] == 42
