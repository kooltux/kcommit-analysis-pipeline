"""Additional tests for lib.pipeline_runtime — progress helpers, print helpers."""
import io, sys, time
import pytest
from unittest.mock import patch

from lib.pipeline_runtime import (
    _fmt_hms, print_stage_input, print_stage_output, finish_progress_line,
    init_pipeline_state, start_stage, finish_stage,
)


def test_fmt_hms_zero():
    assert _fmt_hms(0) == '0:00'


def test_fmt_hms_seconds():
    assert _fmt_hms(45) == '0:45'


def test_fmt_hms_minutes():
    assert _fmt_hms(90) == '1:30'


def test_fmt_hms_hours():
    assert _fmt_hms(3661) == '1:01:01'


def test_fmt_hms_negative():
    assert _fmt_hms(-5) == '0:00'


def test_print_stage_input_list(capsys):
    print_stage_input('commits', list(range(42)))
    captured = capsys.readouterr()
    assert '42' in captured.err or '42' in captured.out


def test_print_stage_input_dict(capsys):
    print_stage_input('map', {'a': 1, 'b': 2})
    captured = capsys.readouterr()
    assert '2' in captured.err or '2' in captured.out


def test_print_stage_input_other(capsys):
    print_stage_input('value', 'hello')
    captured = capsys.readouterr()
    assert 'hello' in captured.err or 'hello' in captured.out


def test_print_stage_output_basic(capsys):
    print_stage_output('prefilter', kept=100)
    captured = capsys.readouterr()
    assert '100' in captured.err or '100' in captured.out


def test_print_stage_output_with_dropped(capsys):
    print_stage_output('prefilter', kept=80, dropped=20)
    captured = capsys.readouterr()
    out = captured.err + captured.out
    assert '80' in out
    assert '20' in out


def test_print_stage_output_with_reasons(capsys):
    print_stage_output('prefilter', kept=80,
                       reasons={'path_blacklist': 15, 'keywords_blacklist': 5})
    captured = capsys.readouterr()
    out = captured.err + captured.out
    assert 'path_blacklist' in out or '15' in out


def test_print_stage_output_with_elapsed(capsys):
    print_stage_output('score', kept=50, elapsed=3.5)
    captured = capsys.readouterr()
    out = captured.err + captured.out
    assert '50' in out


def test_finish_progress_line_no_crash():
    """Must not raise even when stderr is not a TTY."""
    finish_progress_line()


def test_finish_stage_extra_none_no_crash(tmp_path):
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    t0 = start_stage(path, 'some_stage', 1, 8)
    finish_stage(path, 'some_stage', t0, extra=None)


# ── v19.9.1: fixed 25-char/4% bar + three-way determinate/spinner modes ─────

def _capture_stderr_line(monkeypatch, call_kwargs):
    """Force TTY mode, reset internal timing state, call update_stage_progress
    once, and return whatever was written to stderr."""
    import lib.pipeline_runtime as pr
    monkeypatch.setattr(pr, '_STDERR_IS_TTY', True)
    pr._stage_t0.clear()
    pr._last_upd.clear()
    pr._spinner_i.clear()
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stderr', buf)
    pr.update_stage_progress(**call_kwargs)
    return buf.getvalue()


def test_update_stage_progress_bar_is_25_chars_at_50_percent(monkeypatch):
    """50% of a fixed 25-char bar renders 12 filled + 13 empty characters."""
    from lib.pipeline_runtime import _BAR_WIDTH
    assert _BAR_WIDTH == 25
    line = _capture_stderr_line(monkeypatch, dict(
        index=1, total=8, frac=0.5, label='collecting commits',
        n_done=50, n_total=100))
    assert line.count('#') == 12
    assert line.count('-') == 13


def test_update_stage_progress_bar_full_at_100_percent(monkeypatch):
    line = _capture_stderr_line(monkeypatch, dict(
        index=1, total=8, frac=1.0, label='done',
        n_done=100, n_total=100))
    assert line.count('#') == 25
    assert line.count('-') == 0


def test_update_stage_progress_bar_empty_at_0_percent(monkeypatch):
    line = _capture_stderr_line(monkeypatch, dict(
        index=1, total=8, frac=0.0, label='starting',
        n_done=0, n_total=100))
    assert line.count('#') == 0
    assert line.count('-') == 25


def test_update_stage_progress_milestone_frac_without_counts_renders_bar(monkeypatch):
    """When a caller has no n_done/n_total at all but does have a real
    milestone fraction (e.g. st02_build_context.py's 0.10/0.25/.../0.90
    fixed sub-steps), the fixed-width bar is rendered directly from frac --
    this must NOT be downgraded to a spinner, since the caller does have
    genuine positional information."""
    line = _capture_stderr_line(monkeypatch, dict(
        index=2, total=8, frac=0.10, label='loading kernel config',
        n_done=None, n_total=None))
    assert '#' in line
    assert line.count('#') == int(25 * 0.10)
    assert '0/0' not in line


def test_update_stage_progress_milestone_frac_covers_full_range(monkeypatch):
    """Multiple hand-computed milestone fractions all render proportional bars."""
    import lib.pipeline_runtime as pr
    for frac, expected_hashes in [(0.25, 6), (0.55, 13), (0.90, 22)]:
        pr._last_upd.clear(); pr._stage_t0.clear(); pr._spinner_i.clear()
        line = _capture_stderr_line(monkeypatch, dict(
            index=3, total=8, frac=frac, label='step',
            n_done=None, n_total=None))
        assert line.count('#') == expected_hashes, (frac, line)


def test_update_stage_progress_count_without_total_shows_spinner(monkeypatch):
    """A caller with a raw count but a genuinely unknown total (e.g.
    st01_collect.py's unbounded git-log collection loop) shows a spinner
    and the raw count, not a bar."""
    from lib.pipeline_runtime import _SPINNER_FRAMES
    line = _capture_stderr_line(monkeypatch, dict(
        index=1, total=8, frac=0.0, label='collecting commits',
        n_done=250, n_total=None))
    assert any('[%s]' % f in line for f in _SPINNER_FRAMES)
    assert '#' not in line
    assert '250' in line


def test_update_stage_progress_zero_count_no_total_shows_spinner(monkeypatch):
    """n_done=0 (explicitly zero, not None) with n_total=None still counts
    as 'a count exists' -- spinner mode, not the frac-only bar mode."""
    line = _capture_stderr_line(monkeypatch, dict(
        index=1, total=8, frac=0.01, label='collecting commits',
        n_done=0, n_total=None))
    assert '#' not in line


def test_update_stage_progress_spinner_rotates_across_calls(monkeypatch):
    """Successive spinner-mode calls (count known, total unknown) advance
    through the spinner frames."""
    import lib.pipeline_runtime as pr
    monkeypatch.setattr(pr, '_STDERR_IS_TTY', True)
    pr._stage_t0.clear()
    pr._last_upd.clear()
    pr._spinner_i.clear()

    frames_seen = []
    for _ in range(len(pr._SPINNER_FRAMES) + 1):
        buf = io.StringIO()
        monkeypatch.setattr(sys, 'stderr', buf)
        pr._last_upd[(1, 8)] = 0
        pr.update_stage_progress(1, 8, 0.0, 'working', n_done=1, n_total=None)
        out = buf.getvalue()
        for f in pr._SPINNER_FRAMES:
            if ('[%s]' % f) in out:
                frames_seen.append(f)
                break

    assert len(set(frames_seen)) >= 2


def test_update_stage_progress_switches_from_spinner_to_bar(monkeypatch):
    """Once n_total becomes known (count already present), the display
    switches from the spinner to the fixed determinate bar."""
    import lib.pipeline_runtime as pr
    monkeypatch.setattr(pr, '_STDERR_IS_TTY', True)
    pr._stage_t0.clear()
    pr._last_upd.clear()
    pr._spinner_i.clear()

    buf1 = io.StringIO()
    monkeypatch.setattr(sys, 'stderr', buf1)
    pr.update_stage_progress(1, 8, 0.0, 'collecting commits', n_done=10, n_total=None)
    assert '#' not in buf1.getvalue()

    pr._last_upd[(1, 8)] = 0
    buf2 = io.StringIO()
    monkeypatch.setattr(sys, 'stderr', buf2)
    pr.update_stage_progress(1, 8, 0.1, 'collecting commits', n_done=10, n_total=100)
    assert '#' in buf2.getvalue()
    assert '10/100' in buf2.getvalue()


def test_bar_helper_uses_25_char_width():
    """finish_stage()'s _bar() helper matches the same 25-char width."""
    from lib.pipeline_runtime import _bar
    assert _bar(8, 8).count('#') == 25
    assert _bar(0, 8).count('-') == 25
    assert _bar(4, 8).count('#') == 12
