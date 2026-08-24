"""Tests for lib.backport — backport_complexity, backport_tier, pick_priority."""
from lib.backport import (
    compute_backport_complexity,
    compute_pick_priority,
    tier_for_complexity,
    enrich_commit_backport,
    _distinct_top_dirs,
)


# ── tier_for_complexity ──────────────────────────────────────────────────────
def test_tier_boundaries():
    assert tier_for_complexity(0) == 'easy'
    assert tier_for_complexity(24) == 'easy'
    assert tier_for_complexity(25) == 'moderate'
    assert tier_for_complexity(59) == 'moderate'
    assert tier_for_complexity(60) == 'hard'
    assert tier_for_complexity(100) == 'hard'


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
    assert r['tier'] == 'easy'


def test_complexity_large_scattered_commit_is_high():
    c = {'stats': {'files_changed': 80, 'lines_changed': 5000, 'hunks': 120},
         'files': ['drivers/a/x.c', 'net/b/y.c', 'fs/c/z.c', 'arch/arm/d.c'],
         'meta': {}}
    r = compute_backport_complexity(c)
    assert r['complexity'] >= 60
    assert r['tier'] == 'hard'


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
    assert r['tier'] == 'hard'
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
    # top score in run, trivial to backport
    p = compute_pick_priority(score=100, complexity=0, max_score=100)
    assert p == 100


def test_pick_priority_high_score_hard_backport_mid():
    # 0.70*100 + 0.30*(100-100) = 70
    p = compute_pick_priority(score=100, complexity=100, max_score=100)
    assert p == 70


def test_pick_priority_low_score_easy_stays_low():
    # 0.70*0 + 0.30*100 = 30
    p = compute_pick_priority(score=0, complexity=0, max_score=100)
    assert p == 30


def test_pick_priority_zero_max_score_safe():
    # max_score 0 must not divide-by-zero; relevance treated as 0..100 vs 1
    p = compute_pick_priority(score=0, complexity=0, max_score=0)
    assert 0 <= p <= 100


# ── enrich_commit_backport ───────────────────────────────────────────────────
def test_enrich_attaches_all_fields():
    c = {'score': 50, 'stats': {'files_changed': 2, 'lines_changed': 20, 'hunks': 3},
         'files': ['drivers/a.c'], 'meta': {}}
    enrich_commit_backport(c, max_score=100)
    assert isinstance(c['backport_complexity'], int)
    assert c['backport_tier'] in ('easy', 'moderate', 'hard')
    assert isinstance(c['pick_priority'], int)
    assert c['backport']['complexity'] == c['backport_complexity']
    assert 'factors' in c['backport']


def test_enrich_does_not_touch_score():
    c = {'score': 42, 'stats': {'files_changed': 1, 'lines_changed': 1, 'hunks': 1},
         'files': ['a.c'], 'meta': {}}
    enrich_commit_backport(c, max_score=42)
    assert c['score'] == 42
