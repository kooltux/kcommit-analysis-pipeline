"""Tests for lib.logsetup — setup_logging, _use_color, _ColorFormatter."""
import logging
import os
import sys

import pytest

import lib.logsetup as logsetup
from lib.logsetup import setup_logging, _use_color, _ColorFormatter


# ── _use_color ────────────────────────────────────────────────────────────────
def test_no_color_env_disables_color(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')
    monkeypatch.delenv('FORCE_COLOR', raising=False)
    assert _use_color() is False


def test_force_color_env_enables_color(monkeypatch):
    monkeypatch.delenv('NO_COLOR', raising=False)
    monkeypatch.setenv('FORCE_COLOR', '1')
    assert _use_color() is True


def test_no_color_wins_over_force_color(monkeypatch):
    monkeypatch.setenv('NO_COLOR', '1')
    monkeypatch.setenv('FORCE_COLOR', '1')
    assert _use_color() is False


# ── _ColorFormatter ───────────────────────────────────────────────────────────
def _make_record(level=logging.INFO, msg='hello'):
    r = logging.LogRecord('test', level, '', 0, msg, (), None)
    return r


def test_color_formatter_with_color():
    fmt = _ColorFormatter(use_color=True)
    out = fmt.format(_make_record(logging.WARNING, 'warn msg'))
    assert '\033[' in out   # ANSI escape present
    assert 'warn msg' in out


def test_color_formatter_without_color():
    fmt = _ColorFormatter(use_color=False)
    out = fmt.format(_make_record(logging.WARNING, 'warn msg'))
    assert '\033[' not in out
    assert 'warn msg' in out


def test_color_formatter_debug_level():
    fmt = _ColorFormatter(use_color=True)
    out = fmt.format(_make_record(logging.DEBUG, 'debug msg'))
    assert '\033[' in out


def test_color_formatter_error_level():
    fmt = _ColorFormatter(use_color=True)
    out = fmt.format(_make_record(logging.ERROR, 'err'))
    assert '\033[' in out


def test_color_formatter_unknown_level_no_crash():
    fmt = _ColorFormatter(use_color=True)
    out = fmt.format(_make_record(level=99, msg='weird'))
    assert 'weird' in out


# ── setup_logging ─────────────────────────────────────────────────────────────
def _reset_root():
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)


def test_setup_logging_default_level():
    _reset_root()
    setup_logging(verbose=0)
    assert logging.getLogger().level == logging.WARNING


def test_setup_logging_verbose_1():
    _reset_root()
    setup_logging(verbose=1)
    assert logging.getLogger().level == logging.INFO


def test_setup_logging_verbose_2():
    _reset_root()
    setup_logging(verbose=2)
    assert logging.getLogger().level == logging.DEBUG


def test_setup_logging_sets_verbose_global():
    _reset_root()
    setup_logging(verbose=1)
    assert logsetup.VERBOSE == 1


def test_setup_logging_removes_existing_handlers():
    _reset_root()
    root = logging.getLogger()
    dummy = logging.StreamHandler()
    root.addHandler(dummy)
    assert len(root.handlers) >= 1
    setup_logging(verbose=0)
    # After setup, only one handler (the new one) should be present
    assert len(root.handlers) == 1


def test_setup_logging_idempotent():
    _reset_root()
    setup_logging(verbose=0)
    setup_logging(verbose=0)
    assert len(logging.getLogger().handlers) == 1
