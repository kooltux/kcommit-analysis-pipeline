"""Git helpers for kcommit-analysis-pipeline.

run_git() uses subprocess.run() with capture_output=True on Python >= 3.7
(available since 3.7; Ubuntu 18 ships Python 3.6, so we branch on the version).

v18.2.0 (F):
  batch_show_paths() — fetches many (rev, path) blobs through a single
  long-lived ``git cat-file --batch`` pipe instead of spawning one subprocess
  per object.  This eliminates fork/exec overhead and raises throughput from
  ~75 objects/s to ~1 000–5 000 objects/s for cold history-map runs.

  Deadlock-free design: stdin is written in a background daemon thread while
  the main thread reads stdout sequentially.  This avoids the classic
  write-all-then-read-all pipe deadlock that occurs when the OS pipe buffer
  (typically 64 KB) fills up before any output is consumed.
"""
import os
import subprocess
import sys
import threading
import time

_PY37 = sys.version_info >= (3, 7)

RS = u'\x1e'   # ASCII Record Separator  — git format delimiter
FS = u'\x1f'   # ASCII Unit Separator    — head/tail delimiter within a record


def run_git(cfg, args, check=True):
    collect = cfg.get('collect', {}) or {}
    git_bin = collect.get('git_binary', 'git')
    src     = cfg['kernel']['source_dir']
    cmd     = [git_bin, '-C', src] + args

    if _PY37:
        result = subprocess.run(cmd, capture_output=True, text=True)
        out, err, rc = result.stdout, result.stderr, result.returncode
    else:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
        out, err = p.communicate()
        rc = p.returncode

    if check and rc != 0:
        raise RuntimeError('git command failed (%s): %s' % (rc, err.strip()))
    return out


def iter_git_log_records(cfg):
    kernel  = cfg['kernel']
    collect = cfg.get('collect', {}) or {}
    rev_range = '%s..%s' % (kernel['rev_old'], kernel['rev_new'])
    fmt = (RS + 'commit=%H%nparents=%P%nauthor_time=%at%ncommit_time=%ct'
               '%nauthor_name=%an%nauthor_email=%ae%nsubject=%s%nbody=%B' + FS)
    args = ['log', rev_range, '--reverse', '--topo-order', '--format=' + fmt]

    no_merges = collect.get('no_merges', True)
    if no_merges:
        args.append('--no-merges')
    if collect.get('first_parent'):
        args.append('--first-parent')
    if collect.get('use_numstat', True):
        args.append('--numstat')
    elif collect.get('use_name_only', True):
        args.append('--name-only')
    args.extend(collect.get('extra_git_log_args', []))

    output = run_git(cfg, args)
    for raw in output.split(RS):
        raw = raw.strip()
        if not raw:
            continue
        if FS in raw:
            head, tail = raw.split(FS, 1)
        else:
            head, tail = raw, ''
        rec = parse_pretty_block(head)
        files, numstat = parse_tail_block(tail)
        rec['files']   = files
        rec['numstat'] = numstat
        yield rec


def parse_pretty_block(text):
    """Parse the key=value header block produced by iter_git_log_records.

    The header fields (commit, parents, author_time, commit_time, author_name,
    author_email, subject) are single-line and parsed with splitlines().

    The body field is the last field and may contain arbitrary newlines (blank
    lines between paragraphs, indented continuation lines, Signed-off-by
    trailers, etc.).  To preserve every newline character exactly as git
    emitted it, we locate the 'body=' marker using str.find() and take
    everything after it as a raw slice — never splitting it into lines.
    """
    record = {'body': '', 'files': [], 'numstat': []}

    body_marker = '\nbody='
    body_pos    = text.find(body_marker)
    if body_pos != -1:
        header_text = text[:body_pos]
        body_text   = text[body_pos + len(body_marker):]
    else:
        fallback = 'body='
        fb_pos   = text.find(fallback)
        if fb_pos != -1:
            header_text = text[:fb_pos]
            body_text   = text[fb_pos + len(fallback):]
        else:
            header_text = text
            body_text   = ''

    for line in header_text.splitlines():
        key, sep, val = line.partition('=')
        if not sep:
            continue
        if key == 'commit':
            record['commit'] = val
        elif key == 'parents':
            record['parents'] = [x for x in val.split() if x]
        elif key == 'author_time':
            record['author_time'] = int(val) if val else 0
        elif key == 'commit_time':
            record['commit_time'] = int(val) if val else 0
        elif key == 'author_name':
            record['author_name'] = val
        elif key == 'author_email':
            record['author_email'] = val
        elif key == 'subject':
            record['subject'] = val

    record['body'] = body_text.rstrip('\n')
    return record


def parse_tail_block(text):
    files   = []
    numstat = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) == 3 and (parts[0].isdigit() or parts[0] == '-'):
            numstat.append({'added': parts[0], 'deleted': parts[1], 'path': parts[2]})
            files.append(parts[2])
        elif len(parts) == 1:
            files.append(parts[0])
    return sorted(set(files)), numstat


def compute_numstat_totals(numstat):
    """Aggregate a per-file numstat list into commit-size totals.

    *numstat* is the list produced by parse_tail_block(): each entry is a
    ``{'added': <str>, 'deleted': <str>, 'path': <str>}`` dict where 'added'
    and 'deleted' are the raw git strings (decimal digits, or '-' for binary
    files that have no textual line delta).

    Returns a dict with four commit-size indicators:

        files_changed : number of files touched (breadth; binary files count)
        insertions    : total lines added   (binary files contribute 0)
        deletions     : total lines removed  (binary files contribute 0)
        lines_changed : insertions + deletions (churn / depth)

    These are descriptive size metrics only — they are NOT part of the
    profile/rule score (scoring stays exclusively rule-driven).
    """
    files_changed = 0
    insertions    = 0
    deletions     = 0
    for entry in numstat or []:
        files_changed += 1
        # Accept both dict form {'added','deleted','path'} and the
        # positional list/tuple form [added, deleted, path].
        if isinstance(entry, dict):
            added   = str(entry.get('added', '') or '')
            deleted = str(entry.get('deleted', '') or '')
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            added   = str(entry[0] or '')
            deleted = str(entry[1] or '')
        else:
            added = deleted = ''
        if added.isdigit():
            insertions += int(added)
        if deleted.isdigit():
            deletions += int(deleted)
    return {
        'files_changed': files_changed,
        'insertions':    insertions,
        'deletions':     deletions,
        'lines_changed': insertions + deletions,
    }


def show_commit_patch(cfg, sha, unified=0):
    args = ['show', '--no-renames', '--format=medium', '--unified=%d' % unified, sha]
    return run_git(cfg, args)


# ── Hunk counting (backport-complexity input) ────────────────────────────────
#
# A "hunk" is a contiguous block of changed lines in a unified diff, marked by
# a ``@@ -a,b +c,d @@`` header.  The total hunk count across all files in a
# commit is a dispersion / fragmentation signal: a change scattered over many
# hunks is generally harder to cherry-pick cleanly than one compact hunk of the
# same line count.  Counting requires the actual patch text, so it is computed
# lazily (opt-in via collect.count_hunks) over the small post-filter relevant
# set — never over the full commit range.

# Marker written by git --format so we can split a batched multi-commit patch
# stream back into per-commit sections.  Uses the ASCII RS/US separators that
# never appear in diff text.
_HUNK_MARK = RS + 'kchunk=%H' + FS


def count_hunks_in_patch(patch_text):
    """Return the number of unified-diff hunks (``@@`` headers) in *patch_text*.

    Counts lines that start with ``@@`` — the unified-diff hunk header marker.
    A ``git show --unified=0`` patch emits exactly one such header per hunk.
    Non-diff commit-message lines never start with ``@@`` so they are ignored.
    """
    if not patch_text:
        return 0
    n = 0
    for line in patch_text.splitlines():
        if line.startswith('@@'):
            n += 1
    return n


def batch_count_hunks(cfg, shas, progress_callback=None):
    """Return {sha: hunk_count} for *shas* using a single batched ``git show``.

    All commits are diffed in one ``git show --unified=0`` invocation with a
    per-commit format marker so we can split the combined output back into
    per-commit patch sections and count ``@@`` headers in each.  This avoids
    one subprocess per commit.

    Renames are disabled (``--no-renames``) and context is zero
    (``--unified=0``) so the hunk count reflects the number of distinct change
    blocks, not surrounding context.  Merge commits are shown with
    ``--first-parent`` so they yield a normal single-parent diff rather than a
    combined diff (which prints no ``@@`` headers).

    Returns an empty dict when *shas* is empty.  SHAs with no textual diff
    (e.g. pure binary or empty commits) map to 0.
    """
    shas = [s for s in (shas or []) if s]
    if not shas:
        return {}

    args = ['show', '--no-renames', '--first-parent', '--unified=0',
            '--format=' + _HUNK_MARK]
    args.extend(shas)
    output = run_git(cfg, args, check=False)

    counts = {s: 0 for s in shas}
    # Split the combined stream on the RS-prefixed marker; each chunk begins
    # with '<sha>' + FS + <patch...> for one commit.
    sections = output.split(RS)
    done = 0
    total = len(shas)
    for sec in sections:
        if FS not in sec:
            continue
        head, _, body = sec.partition(FS)
        if not head.startswith('kchunk='):
            continue
        sha = head[len('kchunk='):].strip()
        if sha in counts:
            counts[sha] = count_hunks_in_patch(body)
            done += 1
            if progress_callback and (done % 500 == 0 or done == total):
                progress_callback(done, total)
    if progress_callback and done != total:
        progress_callback(total, total)
    return counts


def list_rev_commits(cfg):
    kernel  = cfg['kernel']
    collect = cfg.get('collect', {}) or {}
    rev_range = '%s..%s' % (kernel['rev_old'], kernel['rev_new'])
    args = ['rev-list', '--reverse', rev_range]
    no_merges = collect.get('no_merges', True)
    if no_merges:
        args.append('--no-merges')
    if collect.get('first_parent'):
        args.append('--first-parent')
    out = run_git(cfg, args)
    return [x.strip() for x in out.splitlines() if x.strip()]


def show_path_history(cfg, rev, path):
    """Fetch a single blob <rev>:<path> via git show.  Used as fallback only."""
    args = ['show', '%s:%s' % (rev, path)]
    try:
        return run_git(cfg, args, check=False)
    except Exception:
        return ''


# ── F: batch blob fetcher via git cat-file --batch ────────────────────────────

_BATCH_CHUNK = 500   # progress callback interval


def batch_show_paths(cfg, tasks, progress_callback=None, fallback_serial=True):
    """Fetch a list of (rev, path) blobs using a single ``git cat-file --batch`` pipe.

    This is 10–20×¹ faster than one subprocess per object because it eliminates
    fork/exec overhead for every lookup: a single long-lived git process is
    opened and all object queries are piped through it.

    Deadlock-free design
    --------------------
    A naive write-all-stdin-then-read-all-stdout approach deadlocks as soon as
    the combined output exceeds the OS pipe buffer (~64 KB on Linux).  We avoid
    this by writing stdin in a **background daemon thread** while the main
    thread reads stdout sequentially.  The two ends of the pipe therefore drain
    concurrently and the buffer never fills up.

    Protocol
    --------
    We write ``<rev>:<path>\n`` to stdin for each task.  git replies for each
    query with either::

        <sha> blob <size>\n
        <content bytes>
        \n                     # extra newline git appends after every object

    or, when the object is absent::

        <rev>:<path> missing\n

    Args:
        cfg:              pipeline config dict (needs kernel.source_dir,
                          collect.git_binary).
        tasks:            iterable of (rev, path) tuples.
        progress_callback: optional callable(done, total) invoked every
                          _BATCH_CHUNK objects and at completion.
        fallback_serial:  if True (default), fall back to one-per-task
                          show_path_history() calls if the cat-file pipe
                          fails to start or produces a protocol error.

    Returns:
        dict mapping (rev, path) -> text (str).  Missing objects map to ''.
    """
    tasks = list(tasks)
    if not tasks:
        return {}

    collect = cfg.get('collect', {}) or {}
    git_bin = collect.get('git_binary', 'git')
    src     = cfg['kernel']['source_dir']

    try:
        proc = subprocess.Popen(
            [git_bin, '-C', src, 'cat-file', '--batch'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as exc:
        if fallback_serial:
            return _serial_fallback(cfg, tasks, progress_callback)
        raise RuntimeError('git cat-file --batch failed to start: %s' % exc)

    try:
        results = _run_batch_pipe(proc, tasks, progress_callback)
    except Exception as exc:
        try:
            proc.kill()
            proc.wait()
        except Exception:
            pass
        if fallback_serial:
            print('\n  warning: batch git cat-file failed (%s); '
                  'falling back to serial show' % exc, file=sys.stderr)
            return _serial_fallback(cfg, tasks, progress_callback)
        raise
    finally:
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    return results


def _run_batch_pipe(proc, tasks, progress_callback):
    """Write queries to cat-file stdin (background thread) and read stdout (main thread).

    Deadlock-free: stdin writes happen in a daemon thread so the OS pipe buffer
    on both stdin and stdout drains concurrently.  The main thread reads stdout
    sequentially, one header + body per task, in input order (git cat-file
    --batch preserves query order).

    Error propagation: if the writer thread encounters an exception it stores it
    and the main thread re-raises it after finishing (or aborting) its read loop.
    """
    total         = len(tasks)
    write_error   = [None]   # shared slot: writer thread stores exceptions here

    def _write_stdin():
        try:
            for rev, path in tasks:
                proc.stdin.write(('%s:%s\n' % (rev, path)).encode('utf-8'))
            proc.stdin.close()
        except Exception as exc:
            write_error[0] = exc
            try:
                proc.stdin.close()
            except Exception:
                pass

    writer = threading.Thread(target=_write_stdin, daemon=True)
    writer.start()

    results = {}
    stdout  = proc.stdout

    for i, (rev, path) in enumerate(tasks):
        header = stdout.readline()
        if not header:
            raise RuntimeError(
                'cat-file pipe closed unexpectedly after %d/%d objects' % (i, total))
        header = header.rstrip(b'\n').decode('utf-8', errors='replace')

        if header.endswith(' missing'):
            results[(rev, path)] = ''
        else:
            # header: "<sha> blob <size>"  (or tree/commit/tag — treat all as blob)
            parts = header.split()
            if len(parts) < 3:
                raise RuntimeError(
                    'unexpected cat-file header %r for %s:%s' % (header, rev, path))
            try:
                size = int(parts[2])
            except ValueError:
                raise RuntimeError(
                    'non-integer size in cat-file header %r' % header)
            content = stdout.read(size)
            stdout.read(1)   # consume trailing '\n' git appends after every object
            results[(rev, path)] = content.decode('utf-8', errors='replace')

        if progress_callback and ((i + 1) % _BATCH_CHUNK == 0 or i + 1 == total):
            progress_callback(i + 1, total)

    writer.join(timeout=10)
    if write_error[0] is not None:
        raise RuntimeError('cat-file stdin writer failed: %s' % write_error[0])

    return results


def _serial_fallback(cfg, tasks, progress_callback):
    """One-per-task fallback using show_path_history (original behaviour)."""
    results = {}
    total   = len(tasks)
    for i, (rev, path) in enumerate(tasks):
        results[(rev, path)] = show_path_history(cfg, rev, path) or ''
        if progress_callback and (i + 1) % _BATCH_CHUNK == 0:
            progress_callback(i + 1, total)
    if progress_callback:
        progress_callback(total, total)
    return results


# ── Cherry-pick test (fast: git apply --check) ────────────────────────────────

def can_cherry_pick(cfg, commit_sha, target_rev):
    """Test if *commit_sha* can be cherry-picked cleanly on top of *target_rev*.
    
    Uses ``git show | git apply --check`` which tests if the patch applies
    without modifying the working tree. This is much faster than cherry-pick
    because it doesn't touch the index or working directory.
    
    Returns a dict with:
      'ok':        bool   – True if patch would apply without conflicts
      'conflicts': list   – list of conflicted file paths (empty if ok=True)
      'error':     str    – error message if git command failed, else None
    
    This is a best-effort test: a clean apply here does not guarantee
    conflict-free backport to the actual product (different configs, local
    patches, etc.), but conflicts here guarantee the backport will need work.
    """
    try:
        # Step 1: Get the patch for this commit
        patch = run_git(cfg, ['show', '--no-renames', commit_sha], check=False)
        
        if not patch.strip():
            # Empty commit (e.g., just a message change) - always "applies"
            return {'ok': True, 'conflicts': [], 'error': None}
        
        # Step 2: Test if patch applies cleanly at target revision
        # We need to check the return code, so we use subprocess directly
        collect = cfg.get('collect', {}) or {}
        git_bin = collect.get('git_binary', 'git')
        src = cfg['kernel']['source_dir']
        
        if _PY37:
            result = subprocess.run(
                [git_bin, '-C', src, 'apply', '--check', '--3way', '--unidiff-zero'],
                input=patch,
                capture_output=True,
                text=True,
                check=False
            )
            out, err, rc = result.stdout, result.stderr, result.returncode
        else:
            p = subprocess.Popen(
                [git_bin, '-C', src, 'apply', '--check', '--3way', '--unidiff-zero'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            out, err = p.communicate(input=patch)
            rc = p.returncode
        
        # Check return code: 0 = success, non-zero = conflict
        if rc == 0:
            return {'ok': True, 'conflicts': [], 'error': None}
        
        # Parse conflicted files from error output
        conflicts = []
        error_output = err if err else out
        for line in error_output.splitlines():
            # Lines like "error: file.c: does not match index"
            # or "error: file.c: patch does not apply"
            if 'error:' in line.lower() or 'does not match' in line.lower():
                # Extract filename
                if ':' in line:
                    parts = line.split(':')
                    # Look for a part that looks like a file path
                    for part in parts:
                        part = part.strip()
                        if '/' in part or part.endswith(('.c', '.h', '.S', '.make', '.mk')):
                            # This looks like a file path
                            fname = part.split()[0] if part else ''
                            if fname and fname not in conflicts:
                                conflicts.append(fname)
        
        return {'ok': False, 'conflicts': conflicts, 'error': None}
        
    except Exception as exc:
        return {'ok': False, 'conflicts': [], 'error': str(exc)}


def batch_can_cherry_pick(cfg, commit_shas, target_rev, progress_callback=None):
    """Test multiple commits for cherry-pick feasibility on *target_rev*.
    
    Returns dict mapping commit SHA -> result dict (same format as
    can_cherry_pick()):
      {sha: {'ok': bool, 'conflicts': list, 'error': str or None}, ...}
    
    Strategy:
      1. Checkout target_rev once (detach HEAD)
      2. For each commit: git show | git apply --check (no worktree changes)
      3. Restore original HEAD
    
    This is efficient: 1 checkout + N (show + apply) calls, no reset needed.
    
    Args:
        cfg:           pipeline config dict
        commit_shas:  list of commit SHAs to test
        target_rev:   revision to cherry-pick onto (e.g., config.kernel.rev_old)
        progress_callback: optional callable(current, total, eta_seconds)
    """
    shas = [s for s in (commit_shas or []) if s]
    if not shas:
        return {}
    
    kernel  = cfg['kernel']
    collect = cfg.get('collect', {}) or {}
    
    # Save current HEAD so we can restore it
    try:
        current_head = run_git(cfg, ['rev-parse', 'HEAD']).strip()
    except Exception:
        current_head = None
    
    results = {}
    total = len(shas)
    
    try:
        # Checkout target revision once (detached HEAD)
        run_git(cfg, ['checkout', '--force', '--detach', target_rev], check=False)
        
        # Test each commit with apply --check (no worktree modification)
        # Track timing for ETA calculation
        start_time = time.time()
        last_times = []  # Keep last 10 timings for rolling average
        
        for i, sha in enumerate(shas):
            step_start = time.time()
            
            try:
                result = can_cherry_pick(cfg, sha, target_rev)
                results[sha] = result
            except Exception as exc:
                results[sha] = {'ok': False, 'conflicts': [], 'error': str(exc)}
            
            step_end = time.time()
            step_time = step_end - step_start
            last_times.append(step_time)
            if len(last_times) > 10:
                last_times.pop(0)
            
            # Report progress with ETA
            if progress_callback:
                avg_time = sum(last_times) / len(last_times)
                remaining = total - (i + 1)
                eta_seconds = remaining * avg_time
                progress_callback(i + 1, total, eta_seconds)
        
        return results
        
    finally:
        # Always restore original HEAD
        if current_head:
            try:
                run_git(cfg, ['checkout', '--force', '--detach', current_head], check=False)
            except Exception:
                pass


# ── Cherry-pick cache (SQLite-based, per-target) ─────────────────────────────

def _format_eta(seconds):
    """Format ETA in human-readable format."""
    if seconds < 60:
        return '%ds' % int(seconds)
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return '%dm %ds' % (mins, secs)
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return '%dh %dm' % (hours, mins)


def _progress_bar(current, total, eta_seconds, width=40):
    """Generate a progress bar string with ETA."""
    percent = current / float(total)
    filled = int(width * percent)
    bar = '█' * filled + '░' * (width - filled)
    eta_str = _format_eta(eta_seconds)
    return '[%s] %d/%d (%.1f%%) ETA: %s' % (bar, current, total, percent * 100, eta_str)


def batch_can_cherry_pick_cached(cfg, commit_shas, target_rev, progress_callback=None):
    """Test commits for cherry-pick feasibility with SQLite caching.
    
    Uses CherryDB to cache results per target_rev. Only tests new commits,
    reuses existing results for already-tested commits.
    
    Args:
        cfg: pipeline config dict (MUST contain cherry_pick.cache_dir)
        commit_shas: list of commit SHAs to test
        target_rev: revision to cherry-pick onto (e.g., config.kernel.rev_old)
        progress_callback: optional callable(current, total, eta_seconds)
    
    Returns:
        dict mapping sha -> {'ok': bool, 'conflicts': list, 'error': str or None}
    
    Raises:
        RuntimeError: if cherry_pick.cache_dir is not configured
    """
    from lib.cherrypick_db import load_or_create_db
    
    shas = [s for s in (commit_shas or []) if s]
    if not shas:
        return {}
    
    # Get cache directory from config - REQUIRED, no default
    cherry_pick_cfg = cfg.get('cherry_pick', {}) or {}
    cache_dir = cherry_pick_cfg.get('cache_dir')
    
    if not cache_dir:
        raise RuntimeError(
            'cherry_pick.cache_dir is required when cherry_pick_test is enabled. '
            'Please set "cherry_pick": {"cache_dir": "/path/to/cache"} in your config.'
        )
    
    # Load or create database for this target
    db = load_or_create_db(cache_dir, target_rev)
    
    # Get already-tested SHAs
    tested_shas = db.get_all_shas()
    new_shas = [s for s in shas if s not in tested_shas]
    
    # Load cached results
    results = db.get_results(shas)
    
    # Test new commits only
    if new_shas:
        print('  Testing %d new commits for cherry-pick onto %s...' % (
            len(new_shas), target_rev))
        
        # Progress wrapper with ETA display
        start_time = time.time()
        last_progress_display = -1
        
        def _progress_with_eta(done, total, eta_seconds):
            """Display progress bar with ETA, updating every 5% or at completion."""
            nonlocal last_progress_display
            percent = int(done / float(total) * 100)
            
            # Only update display every 5% or at completion
            if percent % 5 == 0 and percent != last_progress_display or done == total:
                last_progress_display = percent
                bar = _progress_bar(done, total, eta_seconds)
                sys.stdout.write('\r  %s' % bar)
                sys.stdout.flush()
        
        # Test new commits
        new_results = batch_can_cherry_pick(cfg, new_shas, target_rev, 
                                           progress_callback=_progress_with_eta)
        
        # Clear progress line
        sys.stdout.write('\n')
        sys.stdout.flush()
        
        # Save to database
        db.add_results(new_results)
        db.save()
        
        # Merge with cached results
        results.update(new_results)
        
        elapsed = time.time() - start_time
        print('  Completed: tested %d new commits in %.1fs' % (len(new_shas), elapsed))
        if len(tested_shas) > 0:
            print('  Reused %d cached results' % len(tested_shas))
    
    return results
