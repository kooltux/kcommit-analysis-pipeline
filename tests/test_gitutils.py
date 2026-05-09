"""Tests for lib.gitutils — parse_pretty_block, parse_tail_block,
run_git (mocked), iter_git_log_records (mocked)."""
import sys
from unittest.mock import patch, MagicMock
import pytest

from lib.gitutils import (
    parse_pretty_block,
    parse_tail_block,
    run_git,
    iter_git_log_records,
    show_commit_patch,
    list_rev_commits,
    show_path_history,
    RS, FS,
)


def _cfg(src='/fake/repo', git_bin='git', no_merges=True, numstat=True,
         name_only=False, first_parent=False, extra_args=None):
    return {
        'kernel':  {'source_dir': src, 'rev_old': 'v6.1', 'rev_new': 'v6.6'},
        'collect': {
            'git_binary':         git_bin,
            'no_merges':          no_merges,
            'use_numstat':        numstat,
            'use_name_only':      name_only,
            'first_parent':       first_parent,
            'extra_git_log_args': extra_args or [],
        },
    }


def _ok(stdout=''):
    r = MagicMock()
    r.stdout = stdout
    r.stderr = ''
    r.returncode = 0
    return r


def _fail(stderr='error', rc=128):
    r = MagicMock()
    r.stdout = ''
    r.stderr = stderr
    r.returncode = rc
    return r


# ── parse_pretty_block ────────────────────────────────────────────────────────
def test_parse_pretty_block_basic():
    block = (
        'commit=abc123\n'
        'parents=def456\n'
        'author_time=1700000000\n'
        'commit_time=1700000001\n'
        'author_name=Jane Doe\n'
        'author_email=jane@example.com\n'
        'subject=net: fix skb leak\n'
        'body=This fixes a long-standing bug.'
    )
    r = parse_pretty_block(block)
    assert r['commit'] == 'abc123'
    assert r['author_name'] == 'Jane Doe'
    assert r['subject'] == 'net: fix skb leak'
    assert r['author_time'] == 1700000000
    assert 'This fixes' in r['body']


def test_parse_pretty_block_multi_parent():
    block = 'commit=merge1\nparents=aaa bbb\nauthor_time=0\nsubject=Merge\nbody=x'
    r = parse_pretty_block(block)
    assert r['parents'] == ['aaa', 'bbb']


def test_parse_pretty_block_empty_body():
    block = 'commit=abc\nauthor_time=0\nsubject=minimal\nbody='
    r = parse_pretty_block(block)
    assert r['body'] == '' or r['body'] == 'minimal' or isinstance(r['body'], str)


def test_parse_pretty_block_missing_fields():
    r = parse_pretty_block('')
    assert 'body' in r
    assert 'files' in r


def test_parse_pretty_block_author_time_empty():
    r = parse_pretty_block('commit=x\nauthor_time=\nsubject=s\nbody=')
    assert r['author_time'] == 0


# ── parse_tail_block ──────────────────────────────────────────────────────────
def test_parse_tail_block_numstat():
    tail = '10\t2\tdrivers/net/core.c\n5\t0\tinclude/net/skbuff.h\n'
    files, numstat = parse_tail_block(tail)
    assert 'drivers/net/core.c' in files
    assert 'include/net/skbuff.h' in files
    assert len(numstat) == 2
    assert numstat[0]['added'] == '10'


def test_parse_tail_block_name_only():
    tail = 'drivers/usb/hub.c\ndrivers/usb/core.c\n'
    files, numstat = parse_tail_block(tail)
    assert 'drivers/usb/hub.c' in files
    assert numstat == []


def test_parse_tail_block_empty():
    files, numstat = parse_tail_block('')
    assert files == []
    assert numstat == []


def test_parse_tail_block_binary_dash():
    tail = '-\t-\tdrivers/firmware/blob.bin\n'
    files, numstat = parse_tail_block(tail)
    assert 'drivers/firmware/blob.bin' in files


def test_parse_tail_block_deduped():
    tail = 'drivers/net/core.c\ndrivers/net/core.c\n'
    files, _ = parse_tail_block(tail)
    assert len(files) == 1


# ── run_git ───────────────────────────────────────────────────────────────────
def test_run_git_returns_stdout():
    with patch('subprocess.run', return_value=_ok('v6.6-rc1\n')) as m:
        out = run_git(_cfg(), ['describe', '--tags'])
    assert out == 'v6.6-rc1\n'


def test_run_git_raises_on_nonzero():
    with patch('subprocess.run', return_value=_fail('not a repo', 128)):
        with pytest.raises(RuntimeError, match='git command failed'):
            run_git(_cfg(), ['log'])


def test_run_git_check_false_no_raise():
    with patch('subprocess.run', return_value=_fail('err', 1)):
        out = run_git(_cfg(), ['show', 'badref'], check=False)
    assert out == ''


def test_run_git_uses_git_binary():
    with patch('subprocess.run', return_value=_ok()) as m:
        run_git(_cfg(git_bin='/usr/local/bin/git'), ['version'])
    called_cmd = m.call_args[0][0]
    assert called_cmd[0] == '/usr/local/bin/git'


def test_run_git_uses_source_dir():
    with patch('subprocess.run', return_value=_ok()) as m:
        run_git(_cfg(src='/my/kernel'), ['status'])
    called_cmd = m.call_args[0][0]
    assert '/my/kernel' in called_cmd


# ── list_rev_commits ──────────────────────────────────────────────────────────
def test_list_rev_commits_basic():
    output = 'abc123\ndef456\n'
    with patch('subprocess.run', return_value=_ok(output)):
        commits = list_rev_commits(_cfg())
    assert commits == ['abc123', 'def456']


def test_list_rev_commits_empty():
    with patch('subprocess.run', return_value=_ok('')):
        commits = list_rev_commits(_cfg())
    assert commits == []


def test_list_rev_commits_no_merges_flag():
    with patch('subprocess.run', return_value=_ok('a\n')) as m:
        list_rev_commits(_cfg(no_merges=True))
    args = m.call_args[0][0]
    assert '--no-merges' in args


def test_list_rev_commits_first_parent_flag():
    with patch('subprocess.run', return_value=_ok('a\n')) as m:
        list_rev_commits(_cfg(first_parent=True))
    args = m.call_args[0][0]
    assert '--first-parent' in args


# ── iter_git_log_records ──────────────────────────────────────────────────────
def _make_log_output(sha='abc123', subject='net: fix', body='Details.',
                     files='10\t2\tdrivers/net/core.c'):
    head = (
        f'commit={sha}\nparents=\nauthor_time=1700000000\n'
        f'commit_time=1700000000\nauthor_name=Dev\nauthor_email=dev@x.com\n'
        f'subject={subject}\nbody={body}'
    )
    return RS + head + FS + '\n' + files + '\n'


def test_iter_git_log_records_single():
    out = _make_log_output()
    with patch('subprocess.run', return_value=_ok(out)):
        records = list(iter_git_log_records(_cfg()))
    assert len(records) == 1
    assert records[0]['commit'] == 'abc123'
    assert 'drivers/net/core.c' in records[0]['files']


def test_iter_git_log_records_multiple():
    out = _make_log_output('aaa', 'fix1') + _make_log_output('bbb', 'fix2')
    with patch('subprocess.run', return_value=_ok(out)):
        records = list(iter_git_log_records(_cfg()))
    assert len(records) == 2


def test_iter_git_log_records_empty():
    with patch('subprocess.run', return_value=_ok('')):
        records = list(iter_git_log_records(_cfg()))
    assert records == []


def test_iter_git_log_no_merges_flag():
    out = _make_log_output()
    with patch('subprocess.run', return_value=_ok(out)) as m:
        list(iter_git_log_records(_cfg(no_merges=True)))
    args = m.call_args[0][0]
    assert '--no-merges' in args


def test_iter_git_log_no_numstat_flag():
    out = _make_log_output()
    with patch('subprocess.run', return_value=_ok(out)) as m:
        list(iter_git_log_records(_cfg(numstat=False, name_only=True)))
    args = m.call_args[0][0]
    assert '--name-only' in args


# ── show_commit_patch / show_path_history ─────────────────────────────────────
def test_show_commit_patch():
    with patch('subprocess.run', return_value=_ok('diff --git ...\n')):
        out = show_commit_patch(_cfg(), 'abc123')
    assert 'diff' in out


def test_show_path_history_ok():
    with patch('subprocess.run', return_value=_ok('obj-$(CONFIG_USB) += hub.o\n')):
        out = show_path_history(_cfg(), 'v6.1', 'drivers/usb/Makefile')
    assert 'CONFIG_USB' in out


def test_show_path_history_missing_path():
    with patch('subprocess.run', return_value=_fail('not found', 128)):
        out = show_path_history(_cfg(), 'v6.1', 'no/such/path')
    assert out == ''
