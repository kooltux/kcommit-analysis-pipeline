"""Tests for lib.gitutils.batch_can_cherry_pick_cached() unified progress (v19.9.1).

Covers the stage_index/stage_total/label parameters added so cherry-pick
progress renders through the shared lib.pipeline_runtime.update_stage_progress()
bar instead of the standalone block-character bar previously drawn directly
to stdout by _progress_bar()/_format_eta() (both removed in v19.9.1).
"""
from unittest.mock import patch

import pytest

from lib.gitutils import batch_can_cherry_pick_cached
from lib.cherrypick_db import CherryDB


def _cfg(cache_dir):
    return {
        'kernel': {'source_dir': '/fake/repo', 'rev_old': 'v6.1'},
        'collect': {'cherry_pick_cache_dir': str(cache_dir), 'git_binary': 'git'},
    }


def _fake_batch_can_cherry_pick(cfg, shas, target_rev, progress_callback=None,
                                workers=1, result_callback=None):
    """Simulate testing each SHA and invoking both callbacks, like the real
    batch_can_cherry_pick() serial/parallel paths do."""
    total = len(shas)
    results = {}
    for i, sha in enumerate(shas, 1):
        result = {'ok': True, 'conflicts': [], 'error': None}
        results[sha] = result
        if result_callback:
            result_callback(sha, result)
        if progress_callback:
            progress_callback(i, total, 0.0)
    return results


def test_batch_can_cherry_pick_cached_calls_update_stage_progress_when_stage_given(tmp_path):
    """When stage_index/stage_total are passed, progress goes through the
    shared update_stage_progress() renderer instead of a standalone bar."""
    shas = ['%040x' % i for i in range(30)]
    calls = []

    def _capture(index, total, frac, label, n_done=None, n_total=None):
        calls.append({'index': index, 'total': total, 'frac': frac,
                       'label': label, 'n_done': n_done, 'n_total': n_total})

    with patch('lib.gitutils.batch_can_cherry_pick', side_effect=_fake_batch_can_cherry_pick), \
         patch('lib.pipeline_runtime.update_stage_progress', side_effect=_capture), \
         patch('lib.pipeline_runtime.finish_progress_line'):
        batch_can_cherry_pick_cached(
            _cfg(tmp_path), shas, 'v6.1',
            stage_index=5, stage_total=8, label='cherry-pick test')

    assert len(calls) > 0
    assert all(c['index'] == 5 and c['total'] == 8 for c in calls)
    assert all(c['label'] == 'cherry-pick test' for c in calls)
    last = calls[-1]
    assert last['n_done'] == 30
    assert last['n_total'] == 30
    assert last['frac'] == 1.0


def test_batch_can_cherry_pick_cached_no_stage_no_shared_progress_calls(tmp_path):
    """When stage_index/stage_total are omitted, update_stage_progress is
    never invoked (no stage attribution available)."""
    shas = ['%040x' % i for i in range(5)]
    calls = []

    def _capture(*args, **kwargs):
        calls.append((args, kwargs))

    with patch('lib.gitutils.batch_can_cherry_pick', side_effect=_fake_batch_can_cherry_pick), \
         patch('lib.pipeline_runtime.update_stage_progress', side_effect=_capture):
        batch_can_cherry_pick_cached(_cfg(tmp_path), shas, 'v6.1')

    assert calls == []


def test_batch_can_cherry_pick_cached_forwards_to_caller_progress_callback(tmp_path):
    """A caller-supplied progress_callback still receives (done, total, eta)
    even when the shared renderer is also active."""
    shas = ['%040x' % i for i in range(4)]
    caller_calls = []

    def _caller_cb(done, total, eta_seconds):
        caller_calls.append((done, total, eta_seconds))

    with patch('lib.gitutils.batch_can_cherry_pick', side_effect=_fake_batch_can_cherry_pick), \
         patch('lib.pipeline_runtime.update_stage_progress'), \
         patch('lib.pipeline_runtime.finish_progress_line'):
        batch_can_cherry_pick_cached(
            _cfg(tmp_path), shas, 'v6.1', progress_callback=_caller_cb,
            stage_index=5, stage_total=8)

    assert len(caller_calls) == 4
    assert caller_calls[-1][0] == 4
    assert caller_calls[-1][1] == 4


def test_batch_can_cherry_pick_cached_reuses_cached_results(tmp_path):
    """Already-tested SHAs are not re-tested; only new SHAs go through
    batch_can_cherry_pick."""
    cfg = _cfg(tmp_path)
    db = CherryDB(str(tmp_path / 'v6.1'))
    db.add_result('a' * 40, {'ok': True, 'conflicts': [], 'error': None})
    db.save()

    called_with = {}

    def _fake(cfg, shas, target_rev, progress_callback=None, workers=1, result_callback=None):
        called_with['shas'] = shas
        return {}

    with patch('lib.gitutils.batch_can_cherry_pick', side_effect=_fake):
        results = batch_can_cherry_pick_cached(cfg, ['a' * 40, 'b' * 40], 'v6.1')

    assert called_with['shas'] == ['b' * 40]
    assert results['a' * 40]['ok'] is True


def test_batch_can_cherry_pick_cached_empty_shas_returns_empty(tmp_path):
    assert batch_can_cherry_pick_cached(_cfg(tmp_path), [], 'v6.1') == {}


def test_batch_can_cherry_pick_cached_requires_cache_dir():
    cfg = {
        'kernel': {'source_dir': '/fake/repo', 'rev_old': 'v6.1'},
        'collect': {'cherry_pick_cache_dir': None, 'git_binary': 'git'},
    }
    with pytest.raises(RuntimeError, match='cherry_pick_cache_dir'):
        batch_can_cherry_pick_cached(cfg, ['a' * 40], 'v6.1')
