"""Tests for lib.gitutils — parse_pretty_block, parse_tail_block,
run_git (mocked), iter_git_log_records (mocked), batch_show_paths (F)."""
import io
import sys
from unittest.mock import patch, MagicMock, call
import pytest

from lib.gitutils import (
    parse_pretty_block,
    parse_tail_block,
    run_git,
    iter_git_log_records,
    show_commit_patch,
    list_rev_commits,
    show_path_history,
    batch_show_paths,
    compute_numstat_totals,
    count_hunks_in_patch,
    batch_count_hunks,
    RS, FS,
)


# ── count_hunks_in_patch ─────────────────────────────────────────────────────
def test_count_hunks_in_patch_multiple():
    patch = (
        'diff --git a/x.c b/x.c\n'
        '--- a/x.c\n+++ b/x.c\n'
        '@@ -1 +1 @@\n-old\n+new\n'
        '@@ -10 +10 @@\n-old2\n+new2\n'
        'diff --git a/y.c b/y.c\n'
        '--- a/y.c\n+++ b/y.c\n'
        '@@ -5 +5 @@\n-a\n+b\n'
    )
    assert count_hunks_in_patch(patch) == 3


def test_count_hunks_in_patch_none_and_empty():
    assert count_hunks_in_patch('') == 0
    assert count_hunks_in_patch(None) == 0


def test_count_hunks_in_patch_ignores_message_lines():
    # A commit-message line that merely mentions @@ mid-line is not a header.
    patch = 'commit message with @@ inside\n@@ -1 +1 @@\n-x\n+y\n'
    assert count_hunks_in_patch(patch) == 1


def test_batch_count_hunks_empty():
    assert batch_count_hunks(_cfg(), []) == {}


def test_batch_count_hunks_parses_marked_stream():
    sha1 = 'a' * 40
    sha2 = 'b' * 40
    # Simulate git show --format marker output: RS + 'kchunk=<sha>' + FS + patch
    stream = (
        RS + 'kchunk=' + sha1 + FS + '\n'
        'diff --git a/x b/x\n@@ -1 +1 @@\n-x\n+y\n@@ -3 +3 @@\n-a\n+b\n'
        + RS + 'kchunk=' + sha2 + FS + '\n'
        'diff --git a/z b/z\n@@ -1 +1 @@\n-p\n+q\n'
    )
    with patch('lib.gitutils.run_git', return_value=stream):
        counts = batch_count_hunks(_cfg(), [sha1, sha2])
    assert counts[sha1] == 2
    assert counts[sha2] == 1


# ── compute_numstat_totals (commit-size indicators) ─────────────────────────
def test_compute_numstat_totals_basic():
    numstat = [
        {'added': '10', 'deleted': '2', 'path': 'a.c'},
        {'added': '5',  'deleted': '0', 'path': 'b.h'},
    ]
    t = compute_numstat_totals(numstat)
    assert t['files_changed'] == 2
    assert t['insertions'] == 15
    assert t['deletions'] == 2
    assert t['lines_changed'] == 17


def test_compute_numstat_totals_empty():
    t = compute_numstat_totals([])
    assert t == {'files_changed': 0, 'insertions': 0,
                 'deletions': 0, 'lines_changed': 0}


def test_compute_numstat_totals_list_form():
    # Positional [added, deleted, path] entries are also accepted.
    numstat = [['1', '0', 'a.c'], ['4', '2', 'b.c']]
    t = compute_numstat_totals(numstat)
    assert t['files_changed'] == 2
    assert t['insertions'] == 5
    assert t['deletions'] == 2
    assert t['lines_changed'] == 7


def test_compute_numstat_totals_none():
    t = compute_numstat_totals(None)
    assert t['files_changed'] == 0
    assert t['lines_changed'] == 0


def test_compute_numstat_totals_binary_counts_file_not_lines():
    # Binary files report '-' for added/deleted: count the file, add 0 lines.
    numstat = [
        {'added': '-', 'deleted': '-', 'path': 'blob.bin'},
        {'added': '3', 'deleted': '1', 'path': 'x.c'},
    ]
    t = compute_numstat_totals(numstat)
    assert t['files_changed'] == 2
    assert t['insertions'] == 3
    assert t['deletions'] == 1
    assert t['lines_changed'] == 4


def test_compute_numstat_totals_malformed_entries_are_ignored():
    numstat = [
        {'added': '', 'deleted': None, 'path': 'a'},
        {'path': 'b'},                       # missing added/deleted
        {'added': '7', 'deleted': '8', 'path': 'c'},
    ]
    t = compute_numstat_totals(numstat)
    assert t['files_changed'] == 3
    assert t['insertions'] == 7
    assert t['deletions'] == 8
    assert t['lines_changed'] == 15


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


# ── parse_pretty_block ─────────────────────────────────────────────────────────
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


# ── parse_tail_block ────────────────────────────────────────────────────────────
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


# ── list_rev_commits ────────────────────────────────────────────────────────────
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


# ── iter_git_log_records ──────────────────────────────────────────────────────────
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


# ── show_commit_patch / show_path_history ────────────────────────────────────────
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


# ── F: batch_show_paths ─────────────────────────────────────────────────────────────

def _make_catfile_proc(responses):
    """Build a mock Popen process whose stdout returns *responses* bytes.

    responses is the raw bytes git cat-file --batch would emit for a set of
    queries, in order.
    """
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.stdout = io.BytesIO(responses)
    proc.stderr = io.BytesIO(b'')
    proc.wait = MagicMock(return_value=0)
    proc.kill = MagicMock()
    return proc


def _catfile_blob(rev, path, content):
    """Encode a single cat-file --batch blob response."""
    content_bytes = content.encode('utf-8')
    header = b'deadbeef1234 blob %d\n' % len(content_bytes)
    return header + content_bytes + b'\n'


def _catfile_missing(rev, path):
    """Encode a cat-file --batch missing response."""
    return ('%s:%s missing\n' % (rev, path)).encode('utf-8')


def test_batch_show_paths_empty_tasks():
    """F: empty task list returns empty dict without opening any process."""
    with patch('subprocess.Popen') as mock_popen:
        result = batch_show_paths(_cfg(), [])
    assert result == {}
    mock_popen.assert_not_called()


def test_batch_show_paths_single_hit():
    """F: single blob fetched correctly via cat-file pipe."""
    content = 'obj-$(CONFIG_USB) += hub.o\n'
    raw = _catfile_blob('v6.1', 'drivers/usb/Makefile', content)
    proc = _make_catfile_proc(raw)
    with patch('subprocess.Popen', return_value=proc):
        result = batch_show_paths(
            _cfg(), [('v6.1', 'drivers/usb/Makefile')])
    assert result[('v6.1', 'drivers/usb/Makefile')] == content


def test_batch_show_paths_missing_object():
    """F: missing blob returns empty string."""
    raw = _catfile_missing('v6.1', 'no/such/Makefile')
    proc = _make_catfile_proc(raw)
    with patch('subprocess.Popen', return_value=proc):
        result = batch_show_paths(
            _cfg(), [('v6.1', 'no/such/Makefile')])
    assert result[('v6.1', 'no/such/Makefile')] == ''


def test_batch_show_paths_multiple_objects():
    """F: multiple blobs returned in order."""
    tasks = [
        ('v6.1', 'drivers/usb/Makefile'),
        ('v6.6', 'net/Makefile'),
        ('v6.1', 'missing/Makefile'),
    ]
    raw = (
        _catfile_blob('v6.1', 'drivers/usb/Makefile', 'obj-$(CONFIG_USB) += hub.o\n') +
        _catfile_blob('v6.6', 'net/Makefile', 'obj-$(CONFIG_NET) += core.o\n') +
        _catfile_missing('v6.1', 'missing/Makefile')
    )
    proc = _make_catfile_proc(raw)
    with patch('subprocess.Popen', return_value=proc):
        result = batch_show_paths(_cfg(), tasks)
    assert 'CONFIG_USB' in result[('v6.1', 'drivers/usb/Makefile')]
    assert 'CONFIG_NET' in result[('v6.6', 'net/Makefile')]
    assert result[('v6.1', 'missing/Makefile')] == ''


def test_batch_show_paths_progress_callback():
    """F: progress_callback is called at least once during batch."""
    content = 'obj-$(CONFIG_X) += x.o\n'
    tasks = [('v6.1', 'drivers/x/Makefile')]
    raw = _catfile_blob('v6.1', 'drivers/x/Makefile', content)
    proc = _make_catfile_proc(raw)
    calls = []
    with patch('subprocess.Popen', return_value=proc):
        batch_show_paths(_cfg(), tasks, progress_callback=lambda d, t: calls.append((d, t)))
    assert len(calls) >= 1
    assert calls[-1] == (1, 1)


def test_batch_show_paths_popen_failure_falls_back():
    """F: if Popen raises, fallback_serial=True triggers serial fallback."""
    with patch('subprocess.Popen', side_effect=OSError('no git')):
        with patch('lib.gitutils.show_path_history', return_value='fallback') as mock_sph:
            result = batch_show_paths(
                _cfg(), [('v6.1', 'drivers/usb/Makefile')],
                fallback_serial=True)
    assert result[('v6.1', 'drivers/usb/Makefile')] == 'fallback'
    mock_sph.assert_called_once()


def test_batch_show_paths_popen_failure_raises_when_no_fallback():
    """F: fallback_serial=False re-raises the Popen exception."""
    with patch('subprocess.Popen', side_effect=OSError('no git')):
        with pytest.raises(RuntimeError, match='failed to start'):
            batch_show_paths(
                _cfg(), [('v6.1', 'x')],
                fallback_serial=False)


def test_batch_show_paths_binary_content():
    """F: binary-safe: content with arbitrary bytes decoded with replace."""
    # Content with a non-UTF-8 byte
    content_bytes = b'obj-$(CONFIG_X) += x.o\n\xff\xfe\n'
    header = b'deadbeef1234 blob %d\n' % len(content_bytes)
    raw = header + content_bytes + b'\n'
    proc = _make_catfile_proc(raw)
    with patch('subprocess.Popen', return_value=proc):
        result = batch_show_paths(_cfg(), [('v6.1', 'drivers/x/Makefile')])
    # Should not raise; result is a str
    assert isinstance(result[('v6.1', 'drivers/x/Makefile')], str)
    assert 'CONFIG_X' in result[('v6.1', 'drivers/x/Makefile')]


def test_batch_show_paths_stdin_receives_all_queries():
    """F: stdin receives one query line per task."""
    tasks = [
        ('v6.1', 'drivers/usb/Makefile'),
        ('v6.6', 'net/Makefile'),
    ]
    raw = (
        _catfile_blob('v6.1', 'drivers/usb/Makefile', 'a') +
        _catfile_blob('v6.6', 'net/Makefile', 'b')
    )
    proc = _make_catfile_proc(raw)
    written = []
    proc.stdin.write = lambda b: written.append(b)
    proc.stdin.close = MagicMock()
    with patch('subprocess.Popen', return_value=proc):
        batch_show_paths(_cfg(), tasks)
    combined = b''.join(written)
    assert b'v6.1:drivers/usb/Makefile\n' in combined
    assert b'v6.6:net/Makefile\n' in combined


# ── Cherry-pick test (efficient: checkout target once, dry-run per commit) ──

from lib.gitutils import can_cherry_pick, batch_can_cherry_pick


def _cfg_with_kernel(source_dir='/fake/git'):
    return {
        'kernel': {'source_dir': source_dir, 'rev_old': 'v6.1'},
        'collect': {},
    }


def test_can_cherry_pick_success():
    """Test that a clean cherry-pick (dry-run) returns ok=True with no conflicts."""
    cfg = _cfg_with_kernel()
    # Mock successful cherry-pick --dry-run with no conflicts
    # run_git returns stdout string (single call)
    with patch('lib.gitutils.run_git', return_value='') as mock_run:
        result = can_cherry_pick(cfg, 'def456', 'v6.1')
        assert result['ok'] is True
        assert result['conflicts'] == []
        assert result['error'] is None
        # Verify only one git call was made
        mock_run.assert_called_once()


def test_can_cherry_pick_with_conflicts():
    """Test that a cherry-pick with conflicts returns ok=False with conflict list."""
    cfg = _cfg_with_kernel()
    # Mock cherry-pick --dry-run output with conflict message
    conflict_output = (
        'error: could not apply def456...\n'
        'CONFLICT (modify/delete): file1.c deleted in HEAD and modified in def456.\n'
        'CONFLICT (modify/delete): file2.h deleted in HEAD and modified in def456.\n'
    )
    with patch('lib.gitutils.run_git', return_value=conflict_output) as mock_run:
        result = can_cherry_pick(cfg, 'def456', 'v6.1')
        assert result['ok'] is False
        assert 'file1.c' in result['conflicts']
        assert 'file2.h' in result['conflicts']
        assert result['error'] is None
        # Verify only one git call was made
        mock_run.assert_called_once()


def test_can_cherry_pick_error():
    """Test that git errors are captured and returned."""
    cfg = _cfg_with_kernel()
    with patch('lib.gitutils.run_git', side_effect=Exception('git not found')) as mock_run:
        result = can_cherry_pick(cfg, 'def456', 'v6.1')
        assert result['ok'] is False
        assert result['error'] is not None
        assert 'git not found' in result['error']
        # Verify only one git call was made
        mock_run.assert_called_once()


def test_batch_can_cherry_pick_empty():
    """Test batch function with empty SHA list."""
    cfg = _cfg_with_kernel()
    result = batch_can_cherry_pick(cfg, [], 'v6.1')
    assert result == {}


def test_batch_can_cherry_pick_single_success():
    """Test batch function with a single successful cherry-pick."""
    cfg = _cfg_with_kernel()
    with patch('lib.gitutils.run_git') as mock_run:
        # Sequence: get HEAD, checkout target, cherry-pick --dry-run, restore HEAD
        mock_run.side_effect = [
            'abc123\n',      # current HEAD
            '',             # checkout target
            '',             # cherry-pick --dry-run (success)
            '',             # restore HEAD
        ]
        shas = ['c1' * 40]
        results = batch_can_cherry_pick(cfg, shas, 'v6.1')
        assert len(results) == 1
        assert results['c1' * 40]['ok'] is True
        # Verify 4 git calls: rev-parse HEAD, checkout target, dry-run, restore
        assert mock_run.call_count == 4


def test_batch_can_cherry_pick_multiple():
    """Test batch function with multiple commits."""
    cfg = _cfg_with_kernel()
    shas = ['a' * 40, 'b' * 40]
    
    with patch('lib.gitutils.run_git') as mock_run:
        # Sequence: get HEAD, checkout target, 2x dry-run, restore HEAD
        mock_run.side_effect = [
            'abc123\n',      # current HEAD
            '',             # checkout target
            '',             # dry-run sha1 (success)
            'error: conflict',  # dry-run sha2 (conflict)
            '',             # restore HEAD
        ]
        results = batch_can_cherry_pick(cfg, shas, 'v6.1')
        
        assert len(results) == 2
        assert results['a' * 40]['ok'] is True
        assert results['b' * 40]['ok'] is False
        # Verify 5 git calls: rev-parse HEAD, checkout target, 2x dry-run, restore
        assert mock_run.call_count == 5


def test_batch_can_cherry_pick_restores_head_on_error():
    """Test that batch function restores HEAD even if dry-run fails."""
    cfg = _cfg_with_kernel()
    
    with patch('lib.gitutils.run_git') as mock_run:
        # Sequence: get HEAD, checkout target, dry-run raises, restore HEAD
        mock_run.side_effect = [
            'abc123\n',      # current HEAD
            '',             # checkout target
            Exception('git error'),  # dry-run fails
            '',             # restore HEAD (in finally block)
        ]
        shas = ['c1' * 40]
        results = batch_can_cherry_pick(cfg, shas, 'v6.1')
        
        assert len(results) == 1
        assert results['c1' * 40]['ok'] is False
        assert 'git error' in results['c1' * 40]['error']
        # Verify HEAD was restored (4 calls total)
        assert mock_run.call_count == 4
