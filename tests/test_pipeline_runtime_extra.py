"""Additional tests for lib.pipeline_runtime — progress helpers, print helpers."""
import io, sys, time
import pytest
from unittest.mock import patch

from lib.pipeline_runtime import (
    _fmt_hms, print_stage_input, print_stage_output, finish_progress_line,
    init_pipeline_state, start_stage, finish_stage,
)


# ── _fmt_hms ──────────────────────────────────────────────────────────────────
def test_fmt_hms_zero():
    assert _fmt_hms(0) == '0:00'


def test_fmt_hms_seconds():
    assert _fmt_hms(45) == '0:45'


def test_fmt_hms_minutes():
    assert _fmt_hms(90) == '1:30'


def test_fmt_hms_hours():
    assert _fmt_hms(3661) == '1:01:01'


def test_fmt_hms_negative():
    # Negative seconds treated as 0
    assert _fmt_hms(-5) == '0:00'


# ── print_stage_input ─────────────────────────────────────────────────────────
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


# ── print_stage_output ────────────────────────────────────────────────────────
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


# ── finish_progress_line ─────────────────────────────────────────────────────
def test_finish_progress_line_no_crash():
    """Must not raise even when stderr is not a TTY."""
    finish_progress_line()  # just ensure it runs


# ── finish_stage with StageResult-style extra ─────────────────────────────────
def test_finish_stage_extra_none_no_crash(tmp_path):
    path = str(tmp_path / 'state.json')
    init_pipeline_state(path)
    t0 = start_stage(path, 'some_stage', 1, 8)
    finish_stage(path, 'some_stage', t0, extra=None)  # None must not crash
