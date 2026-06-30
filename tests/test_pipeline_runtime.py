"""Tests for lib.pipeline_runtime — StageResult, state machine, stage tracking."""
import json, os, time
import pytest

from lib.pipeline_runtime import (
    StageResult, init_pipeline_state, get_pipeline_state,
    is_stage_done, start_stage, finish_stage, fail_stage,
    wipe_downstream,
)


# ── StageResult ───────────────────────────────────────────────────
def test_stage_result_defaults():
    sr = StageResult()
    assert sr.count   == 0
    assert sr.dropped == 0
    assert sr.reasons == {}
    assert sr.extra   == {}


def test_stage_result_to_extra_dict_with_counts():
    sr = StageResult(count=10, dropped=3, extra={'foo': 'bar'})
    d = sr.to_extra_dict()
    assert d['count']   == 10
    assert d['dropped'] == 3
    assert d['foo']     == 'bar'


def test_stage_result_to_extra_dict_zero_count_omitted():
    """count/dropped are only added when non-zero."""
    sr = StageResult(count=0, dropped=0)
    d = sr.to_extra_dict()
    assert 'count'   not in d
    assert 'dropped' not in d


def test_stage_result_to_extra_dict_extra_not_overwritten():
    """Existing 'count' in extra is not overwritten by to_extra_dict."""
    sr = StageResult(count=5, extra={'count': 99})
    d = sr.to_extra_dict()
    assert d['count'] == 99  # setdefault: original wins


# ── init / get state ─────────────────────────────────────────────────
def test_init_pipeline_state(tmp_path):
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    state = get_pipeline_state(path)
    assert 'stages' in state
    assert 'created_at' in state
    assert state['stages'] == {}


def test_init_pipeline_state_overwrites(tmp_path):
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    init_pipeline_state(path)  # second call must not raise
    state = get_pipeline_state(path)
    assert state['stages'] == {}


# ── is_stage_done ──────────────────────────────────────────────────
def test_is_stage_done_false_before_finish(tmp_path):
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    assert is_stage_done(path, 'collect_commits') is False


def test_is_stage_done_true_after_finish(tmp_path):
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    t0 = start_stage(path, 'collect_commits', 1, 8)
    finish_stage(path, 'collect_commits', t0)
    assert is_stage_done(path, 'collect_commits') is True


# ── start_stage / finish_stage ─────────────────────────────────────────────
def test_finish_stage_records_status_ok(tmp_path):
    """finish_stage merges extra dict directly into the stage record (flat)."""
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    t0 = start_stage(path, 'score_commits', 5, 8)
    finish_stage(path, 'score_commits', t0, status='ok', extra={'count': 42})
    state = get_pipeline_state(path)
    s = state['stages']['score_commits']
    assert s['status'] == 'ok'
    # extra is merged flat into the stage dict, not nested under 'extra'
    assert s['count'] == 42


def test_finish_stage_records_elapsed(tmp_path):
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    t0 = start_stage(path, 'score_commits', 5, 8)
    finish_stage(path, 'score_commits', t0)
    state = get_pipeline_state(path)
    # key is 'duration_sec', not 'elapsed_s'
    assert state['stages']['score_commits']['duration_sec'] >= 0


# ── fail_stage ─────────────────────────────────────────────────────────
def test_fail_stage_records_error(tmp_path):
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    t0 = start_stage(path, 'report_commits', 7, 8)
    fail_stage(path, 'report_commits', t0, error_msg='disk full')
    state = get_pipeline_state(path)
    s = state['stages']['report_commits']
    assert s['status'] == 'failed'
    assert 'disk full' in s.get('error', '')


def test_fail_stage_is_not_done(tmp_path):
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    t0 = start_stage(path, 'report_commits', 7, 8)
    fail_stage(path, 'report_commits', t0)
    assert is_stage_done(path, 'report_commits') is False


# ── wipe_downstream ──────────────────────────────────────────────────
def test_wipe_downstream_clears_later_stages(tmp_path):
    path      = str(tmp_path / 'state.json')
    work_dir  = str(tmp_path)
    cache     = str(tmp_path / 'cache')
    os.makedirs(cache)
    init_pipeline_state(path)

    # Mark stages 0–4 as done
    stage_order = ['prepare_pipeline', 'collect_commits', 'collect_build_context',
                   'build_product_map', 'prefilter_commits',
                   'score_commits', 'postfilter_commits', 'report_commits']
    for key in stage_order[:5]:
        t0 = start_stage(path, key, 0, 8)
        finish_stage(path, key, t0)

    # Wipe from stage 3 (build_product_map) onwards
    wipe_downstream(path, 'build_product_map', work_dir, {}, stage_order)

    state = get_pipeline_state(path)
    assert is_stage_done(path, 'prepare_pipeline')    is True
    assert is_stage_done(path, 'collect_commits')     is True
    assert is_stage_done(path, 'collect_build_context') is True
    assert is_stage_done(path, 'build_product_map')   is False  # wiped
    assert is_stage_done(path, 'prefilter_commits')   is False  # wiped


def test_wipe_downstream_removes_directory(tmp_path):
    """wipe_downstream removes directory entries (e.g. output/commits) via rmtree."""
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    # Create a commits bucket tree
    commits_dir = tmp_path / 'output' / 'commits'
    (commits_dir / 'a' / 'bc').mkdir(parents=True)
    (commits_dir / 'a' / 'bc.json').write_text('{}')
    outputs = {'report_commits': ['output/commits']}
    wipe_downstream(path, 'report_commits', str(tmp_path), outputs,
                    stage_order=['report_commits'])
    assert not commits_dir.exists()


def test_wipe_downstream_removes_files_and_dirs_together(tmp_path):
    """wipe_downstream handles a mix of file and directory output entries."""
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    out = tmp_path / 'output'
    out.mkdir()
    html = out / 'relevant_commits.html'
    html.write_text('<html/>')
    commits_dir = out / 'commits'
    (commits_dir / 'a').mkdir(parents=True)
    (commits_dir / 'a' / 'bc.json').write_text('{}')
    outputs = {'report_commits': ['output/relevant_commits.html', 'output/commits']}
    wipe_downstream(path, 'report_commits', str(tmp_path), outputs,
                    stage_order=['report_commits'])
    assert not html.exists()
    assert not commits_dir.exists()


def test_wipe_downstream_clears_target_stage_state(tmp_path):
    """wipe_downstream sets the target stage status to None even when no files exist."""
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    t0 = start_stage(path, 'report_commits', 7, 8)
    finish_stage(path, 'report_commits', t0)
    assert is_stage_done(path, 'report_commits') is True
    wipe_downstream(path, 'report_commits', str(tmp_path), {},
                    stage_order=['report_commits'])
    assert is_stage_done(path, 'report_commits') is False
    state = get_pipeline_state(path)
    assert state['stages']['report_commits']['status'] is None


def test_wipe_downstream_missing_paths_ignored(tmp_path):
    """wipe_downstream does not raise when listed output files do not exist."""
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    outputs = {'report_commits': [
        'output/nonexistent.html',
        'output/also_missing',
    ]}
    # Must not raise
    wipe_downstream(path, 'report_commits', str(tmp_path), outputs,
                    stage_order=['report_commits'])
