"""Tests for lib.stats and its integration in the progress renderer / run_stage (v20.2.0)."""
import io
import json
import sys
from types import SimpleNamespace

import pytest

from lib import stats


def test_record_writes_one_file_per_host(tmp_path):
    entry = stats.record(str(tmp_path), 'collect_commits', 10.0, commits=100, host='hostA')
    assert (tmp_path / 'hostA.json').is_file()
    data = json.loads((tmp_path / 'hostA.json').read_text(encoding='utf-8'))
    assert data['host'] == 'hostA'
    assert data['entries']['collect_commits']['runs'][0]['seconds'] == 10.0
    assert entry['avg_seconds'] == 10.0 and entry['sec_per_commit'] == 0.1
    assert not (tmp_path / 'hostB.json').exists()


def test_only_the_last_ten_runs_are_kept_and_averages_follow(tmp_path):
    for seconds in range(1, 13):                       # 12 runs: 1..12 s
        stats.record(str(tmp_path), 'k', float(seconds), commits=10, host='h')
    entry = stats.load(str(tmp_path), 'h')['entries']['k']
    assert [r['seconds'] for r in entry['runs']] == [float(s) for s in range(3, 13)]
    assert entry['run_count'] == 10
    assert entry['avg_seconds'] == pytest.approx(7.5)
    assert entry['sec_per_commit'] == pytest.approx(75.0 / 100)


def test_temp_files_are_not_left_behind(tmp_path):
    stats.record(str(tmp_path), 'k', 1.0, host='h')
    assert [p.name for p in tmp_path.iterdir()] == ['h.json']


def test_predict_prefers_item_rate_then_commit_rate_then_average(tmp_path):
    stats.record(str(tmp_path), 'k', 10.0, commits=100, items=50, host='h')
    stats.record(str(tmp_path), 'k', 30.0, commits=100, items=150, host='h')
    d = str(tmp_path)
    assert stats.predict(d, 'k', commits=1000, items=500, host='h') == (pytest.approx(100.0), 2)
    assert stats.predict(d, 'k', commits=1000, host='h') == (pytest.approx(200.0), 2)
    assert stats.predict(d, 'k', host='h') == (pytest.approx(20.0), 2)
    assert stats.predict(d, 'other', host='h') == (None, 0)


def test_predict_scales_with_the_commit_count(tmp_path):
    stats.record(str(tmp_path), 'k', 20.0, commits=1000, host='h')
    assert stats.predict(str(tmp_path), 'k', commits=500, host='h')[0] == pytest.approx(10.0)


def test_remaining_sums_known_stages_and_counts_unknown_ones(tmp_path):
    stats.record(str(tmp_path), 'a', 5.0, host='h')
    stats.record(str(tmp_path), 'b', 7.0, host='h')
    total, unknown = stats.remaining(str(tmp_path), ['a', 'b', 'c'], host='h')
    assert total == pytest.approx(12.0) and unknown == 1


def test_missing_or_corrupt_file_reads_as_empty(tmp_path):
    assert stats.load(str(tmp_path), 'nohost')['entries'] == {}
    (tmp_path / 'bad.json').write_text('{not json', encoding='utf-8')
    assert stats.load(str(tmp_path), 'bad')['entries'] == {}
    (tmp_path / 'odd.json').write_text('[1, 2]', encoding='utf-8')
    assert stats.load(str(tmp_path), 'odd')['entries'] == {}
    # a corrupt file is replaced by the next record
    assert stats.record(str(tmp_path), 'k', 1.0, host='bad') is not None
    assert 'k' in stats.load(str(tmp_path), 'bad')['entries']


@pytest.mark.parametrize('seconds', [0, -1, None])
def test_nothing_recorded_for_unusable_durations_or_without_directory(tmp_path, seconds):
    assert stats.record(str(tmp_path), 'k', seconds, host='h') is None
    assert stats.record(None, 'k', 5.0, host='h') is None
    assert list(tmp_path.iterdir()) == []


def test_io_errors_never_raise(tmp_path):
    blocker = tmp_path / 'file'
    blocker.write_text('x', encoding='utf-8')
    assert stats.record(str(blocker / 'sub'), 'k', 1.0, host='h') is None


def test_host_name_is_file_name_safe(monkeypatch):
    monkeypatch.setattr(stats.socket, 'gethostname', lambda: 'my host/..:x')
    assert stats.host_name() == 'my_host_.._x'
    assert stats.stats_file('/s', 'h') == '/s/h.json'


def test_format_duration():
    assert stats.format_duration(0) == '0:00'
    assert stats.format_duration(75) == '1:15'
    assert stats.format_duration(3725) == '1:02:05'


# ── renderer integration ────────────────────────────────────────────────────
@pytest.fixture
def runtime(tmp_path, monkeypatch):
    import lib.pipeline_runtime as pr
    monkeypatch.setattr(pr, '_STDERR_IS_TTY', False)
    pr.set_stats(str(tmp_path / 'st'), run_size=1000)
    monkeypatch.setattr(stats, 'host_name', lambda: 'h')
    yield pr
    pr.set_stats(None)


def test_a_finished_step_with_a_total_is_recorded_per_stage_and_label(runtime, tmp_path, monkeypatch):
    pr = runtime
    clock = iter([100.0, 110.0, 110.0, 110.0])
    monkeypatch.setattr(pr.time, 'monotonic', lambda: next(clock, 999.0))
    pr.update_stage_progress(1, 9, 0.0, 'counting hunks', n_done=0, n_total=400)
    pr.update_stage_progress(1, 9, 0.5, 'next step', n_done=1, n_total=10)   # label change closes the first
    entry = stats.load(str(tmp_path / 'st'), 'h')['entries']['collect_commits/counting hunks']
    run = entry['runs'][0]
    assert run['seconds'] == 10.0 and run['items'] == 400 and run['commits'] == 1000
    assert entry['sec_per_item'] == pytest.approx(10.0 / 400)


def test_steps_without_total_or_too_short_are_not_recorded(runtime, tmp_path):
    pr = runtime
    pr.update_stage_progress(0, 9, 0.5, 'milestone')            # no counts
    pr.update_stage_progress(0, 9, 0.9, 'other milestone')
    pr.update_stage_progress(1, 9, 0.0, 'quick', n_done=0, n_total=5)
    pr.update_stage_progress(1, 9, 1.0, 'quick done', n_done=5, n_total=5)   # < 0.5 s
    assert stats.load(str(tmp_path / 'st'), 'h')['entries'] == {}


def test_open_step_is_recorded_when_the_stage_finishes(runtime, tmp_path, monkeypatch, capsys):
    pr = runtime
    state = str(tmp_path / 'state.json')
    pr.init_pipeline_state(state)
    started = pr.start_stage(state, 'collect_commits', 1, 9)
    clock = iter([5.0, 8.0])
    monkeypatch.setattr(pr.time, 'monotonic', lambda: next(clock, 999.0))
    pr.update_stage_progress(1, 9, 0.0, 'collecting commits', n_done=0, n_total=60)
    pr.finish_stage(state, 'collect_commits', started)
    entry = stats.load(str(tmp_path / 'st'), 'h')['entries']['collect_commits/collecting commits']
    assert entry['runs'][0]['seconds'] == 3.0 and entry['runs'][0]['items'] == 60


def test_failed_stage_is_not_recorded(runtime, tmp_path, monkeypatch):
    pr = runtime
    state = str(tmp_path / 'state.json')
    pr.init_pipeline_state(state)
    started = pr.start_stage(state, 'collect_commits', 1, 9)
    pr.update_stage_progress(1, 9, 0.0, 'collecting commits', n_done=0, n_total=60)
    pr.fail_stage(state, 'collect_commits', started, 'boom')
    assert stats.load(str(tmp_path / 'st'), 'h')['entries'] == {}


def test_eta_shows_the_prediction_until_a_live_rate_exists(runtime, tmp_path, monkeypatch):
    pr = runtime
    monkeypatch.setattr(pr, '_STDERR_IS_TTY', True)
    stats.record(str(tmp_path / 'st'), 'collect_commits/counting hunks', 100.0, items=1000, host='h')
    pr._stage_t0.clear(); pr._last_upd.clear()
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stderr', buf)
    pr.update_stage_progress(1, 9, 0.0, 'counting hunks', n_done=0, n_total=500)
    assert 'ETA ~' in buf.getvalue()           # 500 items * 0.1 s/item
    pr._last_upd.clear()
    buf2 = io.StringIO()
    monkeypatch.setattr(sys, 'stderr', buf2)
    pr.update_stage_progress(1, 9, 0.5, 'counting hunks', n_done=250, n_total=500)
    assert 'ETA ~' not in buf2.getvalue() and 'ETA ' in buf2.getvalue()


def test_no_prediction_without_history(runtime, monkeypatch):
    pr = runtime
    monkeypatch.setattr(pr, '_STDERR_IS_TTY', True)
    pr._stage_t0.clear(); pr._last_upd.clear()
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stderr', buf)
    pr.update_stage_progress(1, 9, 0.0, 'never seen', n_done=0, n_total=500)
    assert 'ETA' not in buf.getvalue()


# ── command integration ─────────────────────────────────────────────────────
def test_print_estimate_uses_history_and_is_silent_without(tmp_path, capsys, monkeypatch):
    from lib.commands.base import print_estimate
    monkeypatch.setattr(stats, 'host_name', lambda: 'h')
    cfg = {'paths': {'stats_dir': str(tmp_path / 'st')}}
    args = SimpleNamespace(progress_json=False)
    state = str(tmp_path / 'state.json')
    print_estimate(cfg, state, ['a', 'b'], args, 'estimated total time')
    assert capsys.readouterr().out == ''                      # no history yet
    stats.record(str(tmp_path / 'st'), 'a', 65.0, host='h')
    print_estimate(cfg, state, ['a', 'b'], args, 'estimated total time')
    out = capsys.readouterr().out
    assert 'estimated total time: 1:05' in out and '1 stage(s) without history' in out
    print_estimate(cfg, state, ['a', 'b'], SimpleNamespace(progress_json=True), 'x')
    assert capsys.readouterr().out == ''                      # --progress-json stays clean
    print_estimate({'paths': {}}, state, ['a'], args, 'x')
    assert capsys.readouterr().out == ''                      # no stats_dir configured


def test_run_stage_records_the_stage_and_announces_the_estimate_next_time(tmp_path, monkeypatch, capsys):
    import time
    import lib.pipeline_runtime as pr
    from lib.commands import base
    monkeypatch.setattr(stats, 'host_name', lambda: 'h')
    monkeypatch.setattr(pr, '_RUN_SIZE', None)
    state = str(tmp_path / 'state.json')
    base.init_pipeline_state(state)
    cfg = {'paths': {'stats_dir': str(tmp_path / 'st'), 'output_dir': str(tmp_path / 'out')}}
    args = SimpleNamespace(force=True, resume=False, progress_json=False)

    def stage(cfg_, cache_):
        time.sleep(0.02)
        return [{'commit': 'x'}] * 40

    base.run_stage(1, 'collect_commits', stage, cfg, str(tmp_path), str(tmp_path), state, args)
    assert 'estimated duration' not in capsys.readouterr().out          # first run: no history
    runs = stats.load(str(tmp_path / 'st'), 'h')['entries']['collect_commits']['runs']
    assert len(runs) == 1 and runs[0]['commits'] == 40 and runs[0]['seconds'] >= 0.02
    base.run_stage(1, 'collect_commits', stage, cfg, str(tmp_path), str(tmp_path), state, args)
    assert 'estimated duration' in capsys.readouterr().out
    assert len(stats.load(str(tmp_path / 'st'), 'h')['entries']['collect_commits']['runs']) == 2


def test_run_stage_without_stats_dir_writes_nothing(tmp_path, capsys):
    from lib.commands import base
    state = str(tmp_path / 'state.json')
    base.init_pipeline_state(state)
    args = SimpleNamespace(force=True, resume=False, progress_json=False)
    base.run_stage(1, 'collect_commits', lambda c, k: [], {'paths': {}}, str(tmp_path),
                   str(tmp_path), state, args)
    assert sorted(p.name for p in tmp_path.iterdir()) == ['state.json']


def test_run_size_comes_from_the_collect_commits_state(tmp_path):
    from lib.commands.base import run_size_from_state
    state = tmp_path / 'state.json'
    assert run_size_from_state(str(state)) is None
    state.write_text(json.dumps({'stages': {'collect_commits': {'commit_count': 321}}}), encoding='utf-8')
    assert run_size_from_state(str(state)) == 321
    state.write_text(json.dumps({'stages': {'collect_commits': {'commit_count': 0}}}), encoding='utf-8')
    assert run_size_from_state(str(state)) is None
