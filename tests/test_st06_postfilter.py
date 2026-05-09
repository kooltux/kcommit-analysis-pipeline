"""Tests for lib.stages.st06_postfilter — run(), _get_threshold, rank assignment."""
import json, os
import pytest

from lib.stages.st06_postfilter import run, _get_threshold
from lib.manifest import CACHE_FILES


def _scored_commit(sha, score, rank=None):
    c = {'commit': sha, 'subject': f'fix: {sha}', 'score': score,
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


# ── _get_threshold ─────────────────────────────────────────────────────────
def test_get_threshold_default():
    assert _get_threshold({}) == 0.0

def test_get_threshold_from_filter():
    assert _get_threshold({'filter': {'min_score': 25}}) == 25.0

def test_get_threshold_ignores_reports():
    assert _get_threshold({'reports': {'min_score': 99}}) == 0.0

def test_get_threshold_bad_value_returns_zero():
    assert _get_threshold({'filter': {'min_score': 'high'}}) == 0.0


# ── run(): rank assignment ─────────────────────────────────────────────────
def test_run_assigns_rank(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    commits = [_scored_commit('aaa', 50), _scored_commit('bbb', 80),
               _scored_commit('ccc', 30)]
    _write_json(os.path.join(cache, CACHE_FILES['scored']), commits)
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [])

    relevant, low, thresh = run({}, cache)
    # Should be sorted descending by score
    assert [c['commit'] for c in relevant] == ['bbb', 'aaa', 'ccc']
    assert [c['_rank'] for c in relevant] == [1, 2, 3]
    assert thresh == 0.0
    assert low == []


# ── run(): threshold drops commits ────────────────────────────────────────
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


# ── run(): dropped written to dedicated postfilter cache ───────────────────
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


# ── run(): relevant written to cache ──────────────────────────────────────
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


# ── run(): empty scored list ───────────────────────────────────────────────
def test_run_empty_scored(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']), [])
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [])
    relevant, low, _ = run({}, cache)
    assert relevant == []
    assert low == []


# ── run(): zero-score commits kept when no threshold ─────────────────────
def test_run_zero_score_kept_without_threshold(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write_json(os.path.join(cache, CACHE_FILES['scored']),
                [_scored_commit('zero', 0)])
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [])
    relevant, low, _ = run({}, cache)
    assert len(relevant) == 1
    assert low == []
