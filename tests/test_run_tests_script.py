"""run_tests: parallel by default, arguments forwarded, log, clipboard and exit status."""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'run_tests'
DEFAULT = ['-m', 'pytest', '--color=no', '-n', 'logical']


def invoke(tmp_path, status=0, args=(), display=False, xdist=True):
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    python = bindir / 'python3'
    python.write_text('#!/bin/bash\nif [ "$1" = -c ]; then [ "$FAKE_XDIST" = yes ]; exit; fi\nprintf "ARG:%s\\n" "$@"\necho "FAILED tests/x.py::test_it"\nexit "$STATUS"\n')
    python.chmod(0o700)
    clip = bindir / 'xclip'
    clip.write_text('#!/bin/bash\ncat > "$CLIP"\necho copied >> "$CLIP_COUNT"\n')
    clip.chmod(0o700)
    env = {key: value for key, value in os.environ.items() if key != 'DISPLAY'}
    env.update(PATH=str(bindir) + os.pathsep + env['PATH'], STATUS=str(status),
               FAKE_XDIST='yes' if xdist else 'no',
               CLIP=str(tmp_path / 'clip'), CLIP_COUNT=str(tmp_path / 'clip-count'),
               KCAP_TEST_LOG=str(tmp_path / 'run.log'))
    if display:
        env['DISPLAY'] = ':test'
    result = subprocess.run(['bash', str(SCRIPT), *args], env=env, capture_output=True,
                            text=True, timeout=30)
    forwarded = [line[4:] for line in result.stdout.splitlines() if line.startswith('ARG:')]
    return result, forwarded, (tmp_path / 'run.log').read_text()


def test_parallel_by_default(tmp_path):
    result, forwarded, log = invoke(tmp_path, args=('tests/x.py',))
    assert forwarded == [*DEFAULT, 'tests/x.py']


def test_arguments_are_forwarded_unchanged_and_later_n_wins(tmp_path):
    args = ('-n', '4', '-k', 'alpha or beta', '--', '-n8', 'a b')
    result, forwarded, log = invoke(tmp_path, args=args)
    assert forwarded == [*DEFAULT, *args]


def test_serial_run_without_xdist(tmp_path):
    result, forwarded, log = invoke(tmp_path, args=('tests/x.py',), xdist=False)
    assert forwarded == ['-m', 'pytest', '--color=no', 'tests/x.py']
    assert 'run_tests: tests run by default serially (pytest-xdist not available)' in log
    assert result.returncode == 0


def test_log_announces_the_parallel_default(tmp_path):
    result, forwarded, log = invoke(tmp_path)
    assert 'run_tests: tests run by default in parallel (-n logical)' in log


def test_serial_run_can_be_requested(tmp_path):
    result, forwarded, log = invoke(tmp_path, args=('-n', '0', '--pdb'))
    assert forwarded[-3:] == ['-n', '0', '--pdb']


@pytest.mark.parametrize('status', [0, 1, 3])
def test_pytest_runs_once_and_status_is_returned(tmp_path, status):
    result, forwarded, log = invoke(tmp_path, status)
    assert result.returncode == status and f'run_tests: exit status {status}' in result.stdout
    assert log.count('ARG:-m') == 1 and result.stdout.count('ARG:-m') == 1


def test_failure_report_reaches_log_and_clipboard(tmp_path):
    result, forwarded, log = invoke(tmp_path, 1, display=True)
    assert 'FAILED tests/x.py::test_it' in log and str(tmp_path / 'run.log') in result.stdout
    assert (tmp_path / 'clip').read_text() == log
    assert (tmp_path / 'clip-count').read_text() == 'copied\n'
    assert 'the log was copied to the clipboard' in result.stdout


def test_without_display_nothing_is_copied(tmp_path):
    result, forwarded, log = invoke(tmp_path)
    assert not (tmp_path / 'clip').exists() and 'NOT copied to the clipboard' in result.stdout


def test_log_starts_with_the_invocation(tmp_path):
    result, forwarded, log = invoke(tmp_path, args=('-k', 'alpha or beta', 'tests/x.py'))
    lines = log.splitlines()
    assert lines[0].startswith('run_tests: invoked as: ') and str(SCRIPT) in lines[0]
    assert lines[0].strip().endswith('-k alpha\\ or\\ beta tests/x.py')
    assert lines[1] == ('run_tests: pytest command: python3 -m pytest --color=no -n logical '
                        '-k alpha\\ or\\ beta tests/x.py ')
    assert lines[2] == 'run_tests: working directory: ' + str(SCRIPT.parent)
    assert 'run_tests: invoked as:' in result.stdout
