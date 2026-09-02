"""Tests for lib.cherrypick_script_gen -- cherry-pick execution script generation."""
import os
import stat
import subprocess
from unittest.mock import patch

import pytest

from lib.cherrypick_script_gen import (
    build_cherry_pick_script, write_cherry_pick_script,
    _load_commits, _index_shas_and_subjects,
)
from lib.cherrypick_db import load_or_create_db
from lib.manifest import CACHE_FILES
from lib.config import save_json


def _cfg(tmp_path, rev_old='v6.1', rev_new='v6.6', cache_dir_name='cpcache'):
    return {
        'kernel': {
            'source_dir': str(tmp_path / 'src'),
            'rev_old': rev_old,
            'rev_new': rev_new,
        },
        'collect': {
            'cherry_pick_cache_dir': str(tmp_path / cache_dir_name),
        },
    }


def _commit(sha, subject='fix: something'):
    return {'commit': sha, 'subject': subject}


def _write_cache(cache, cache_key, commits):
    save_json(os.path.join(cache, CACHE_FILES[cache_key]), commits)


def _seed_db(cfg, results):
    """results: dict sha -> {'ok': bool}"""
    collect = cfg['collect']
    db = load_or_create_db(collect['cherry_pick_cache_dir'], cfg['kernel']['rev_old'])
    for sha, res in results.items():
        db.add_result(sha, res)
    db.save()


# ── _index_shas_and_subjects (v19.4.1) ───────────────────────────

def test_index_shas_and_subjects_dedup_preserves_first_order():
    commits = [
        {'commit': 'aaa', 'subject': 's1'},
        {'commit': 'bbb', 'subject': 's2'},
        {'commit': 'aaa', 'subject': 's1-dup'},
        {'commit': 'ccc', 'subject': 's3'},
    ]
    shas, subjects = _index_shas_and_subjects(commits)
    assert shas == ['aaa', 'bbb', 'ccc']
    assert subjects['aaa'] == 's1'  # first occurrence wins
    assert subjects['ccc'] == 's3'


def test_index_shas_and_subjects_skips_entries_without_sha():
    commits = [{'commit': 'a', 'subject': 'x'}, {'subject': 'no-sha'}, {}]
    shas, subjects = _index_shas_and_subjects(commits)
    assert shas == ['a']


def test_load_commits_reads_file_exactly_once(tmp_path):
    """v19.4.1 regression: the O(N^2) bug came from re-opening the cache file
    once per commit.  build_cherry_pick_script() must call the file-loading
    path exactly once per invocation, not once per SHA."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    many = [_commit('sha%03d' % i) for i in range(50)]
    _write_cache(cache, 'relevant', many)
    _seed_db(cfg, {c['commit']: {'ok': True} for c in many})

    with patch('lib.cherrypick_script_gen.list_rev_commits',
              return_value=[c['commit'] for c in many]), \
         patch('lib.cherrypick_script_gen.load_json',
              wraps=__import__('lib.config', fromlist=['load_json']).load_json) as spy:
        text, stats = build_cherry_pick_script(cfg, cache, 'relevant')

    assert text is not None
    assert stats['cherry_pickable'] == 50
    # Exactly one call should target the relevant_commits.json cache file
    # (the CherryDB itself uses sqlite, not load_json, so no extra calls
    # from that path).
    cache_file_calls = [c for c in spy.call_args_list
                        if CACHE_FILES['relevant'] in (c.args[0] if c.args else c.kwargs.get('path', ''))]
    assert len(cache_file_calls) == 1, (
        'Expected exactly 1 load_json() call for the cache file, got %d '
        '-- possible regression of the O(N^2) file-read bug'
        % len(cache_file_calls)
    )


# ── build_cherry_pick_script: ordering ────────────────────────────

def test_script_orders_by_git_history_not_by_cache_order(tmp_path):
    """Cache lists commits in reverse-of-history order; script must still
    emit them in git-history (oldest -> newest) order."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    # Cache order is newest-first (opposite of git history) to prove the
    # generator does not trust the cache's own ordering.
    _write_cache(cache, 'relevant', [_commit('c3'), _commit('c2'), _commit('c1')])
    _seed_db(cfg, {'c1': {'ok': True}, 'c2': {'ok': True}, 'c3': {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['c1', 'c2', 'c3']):
        text, stats = build_cherry_pick_script(cfg, cache, 'relevant')

    assert text is not None
    idx_c1 = text.index('git cherry-pick c1')
    idx_c2 = text.index('git cherry-pick c2')
    idx_c3 = text.index('git cherry-pick c3')
    assert idx_c1 < idx_c2 < idx_c3
    assert stats['cherry_pickable'] == 3


def test_script_ignores_date_or_score_rank_and_uses_history_order(tmp_path):
    """Even if cache entries carry misleading rank/date-like fields, only
    git-history order (from list_rev_commits) determines emission order."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [
        {'commit': 'newest', '_rank': 1, 'author_time': 999},
        {'commit': 'oldest', '_rank': 2, 'author_time': 1},
        {'commit': 'middle', '_rank': 3, 'author_time': 500},
    ])
    _seed_db(cfg, {'oldest': {'ok': True}, 'middle': {'ok': True}, 'newest': {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits',
              return_value=['oldest', 'middle', 'newest']):
        text, stats = build_cherry_pick_script(cfg, cache, 'relevant')

    order = [text.index('git cherry-pick %s' % s) for s in ('oldest', 'middle', 'newest')]
    assert order == sorted(order)


# ── build_cherry_pick_script: filtering ──────────────────────────

def test_only_ok_true_commits_included(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('good'), _commit('bad'), _commit('untested')])
    _seed_db(cfg, {'good': {'ok': True}, 'bad': {'ok': False}})

    with patch('lib.cherrypick_script_gen.list_rev_commits',
              return_value=['good', 'bad', 'untested']):
        text, stats = build_cherry_pick_script(cfg, cache, 'relevant')

    assert 'git cherry-pick good' in text
    assert 'git cherry-pick bad' not in text
    assert 'git cherry-pick untested' not in text
    assert stats['total_in_set'] == 3
    assert stats['tested'] == 2
    assert stats['cherry_pickable'] == 1
    assert stats['skipped_conflict'] == 1
    assert stats['skipped_untested'] == 1


def test_prefiltered_vs_relevant_use_different_cache_keys(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'prefilter_kept', [_commit('p1'), _commit('p2')])
    _write_cache(cache, 'relevant', [_commit('p1')])
    _seed_db(cfg, {'p1': {'ok': True}, 'p2': {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['p1', 'p2']):
        text_pf, stats_pf = build_cherry_pick_script(cfg, cache, 'prefilter_kept')
        text_rel, stats_rel = build_cherry_pick_script(cfg, cache, 'relevant')

    assert stats_pf['total_in_set'] == 2
    assert stats_rel['total_in_set'] == 1
    assert 'git cherry-pick p2' in text_pf
    assert 'git cherry-pick p2' not in text_rel


# ── build_cherry_pick_script: edge cases ─────────────────────────

def test_empty_commit_set_returns_none(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [])
    text, stats = build_cherry_pick_script(cfg, cache, 'relevant')
    assert text is None
    assert stats['total_in_set'] == 0


def test_missing_cherry_pick_cache_dir_returns_none(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    cfg['collect'].pop('cherry_pick_cache_dir')
    _write_cache(cache, 'relevant', [_commit('a')])
    text, stats = build_cherry_pick_script(cfg, cache, 'relevant')
    assert text is None
    assert stats['skipped_untested'] == 1


def test_missing_rev_old_returns_none(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    cfg['kernel'].pop('rev_old')
    _write_cache(cache, 'relevant', [_commit('a')])
    text, stats = build_cherry_pick_script(cfg, cache, 'relevant')
    assert text is None


def test_no_cherry_db_yet_returns_none(tmp_path):
    """CherryDB has never been created for this rev_old -- treat as untested."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a')])
    text, stats = build_cherry_pick_script(cfg, cache, 'relevant')
    assert text is None
    assert stats['skipped_untested'] == 1


def test_all_tested_but_none_ok_returns_none(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a'), _commit('b')])
    _seed_db(cfg, {'a': {'ok': False}, 'b': {'ok': False}})
    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a', 'b']):
        text, stats = build_cherry_pick_script(cfg, cache, 'relevant')
    assert text is None
    assert stats['cherry_pickable'] == 0
    assert stats['skipped_conflict'] == 2


def test_history_order_missing_sha_still_included_at_end(tmp_path):
    """If list_rev_commits() (e.g. due to no_merges) omits an ok=True SHA,
    it must still appear in the script rather than being silently dropped."""
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a'), _commit('merge_commit')])
    _seed_db(cfg, {'a': {'ok': True}, 'merge_commit': {'ok': True}})
    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a']):
        text, stats = build_cherry_pick_script(cfg, cache, 'relevant')
    assert 'git cherry-pick a' in text
    assert 'git cherry-pick merge_commit' in text
    assert stats['cherry_pickable'] == 2


# ── script content ───────────────────────────────────────────────────

def test_script_has_shebang_and_strict_mode(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a')])
    _seed_db(cfg, {'a': {'ok': True}})
    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a']):
        text, _ = build_cherry_pick_script(cfg, cache, 'relevant')
    assert text.startswith('#!/usr/bin/env bash\n')
    assert 'set -euo pipefail' in text


def test_script_header_reports_counts(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a'), _commit('b'), _commit('c')])
    _seed_db(cfg, {'a': {'ok': True}, 'b': {'ok': False}})
    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a', 'b', 'c']):
        text, stats = build_cherry_pick_script(cfg, cache, 'relevant')
    assert '3 commit(s) in set' in text
    assert '2 tested' in text
    assert '1 cherry-pickable' in text
    assert '1 untested' in text
    assert '1 with conflicts' in text


def test_script_includes_subject_as_comment(tmp_path):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a', subject='net: fix leak')])
    _seed_db(cfg, {'a': {'ok': True}})
    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a']):
        text, _ = build_cherry_pick_script(cfg, cache, 'relevant')
    assert 'git cherry-pick a  # net: fix leak' in text


# ── write_cherry_pick_script: filesystem side effects ─────────────────

def test_write_creates_executable_file(tmp_path):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a')])
    _seed_db(cfg, {'a': {'ok': True}})
    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a']):
        path, stats = write_cherry_pick_script(cfg, cache, outdir, 'relevant', 'cherry_pick_relevant.sh')
    assert path is not None
    assert os.path.exists(path)
    mode = os.stat(path).st_mode
    assert mode & stat.S_IXUSR
    with open(path) as f:
        content = f.read()
    assert 'git cherry-pick a' in content


def test_write_returns_none_path_when_nothing_cherry_pickable(tmp_path):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [])
    path, stats = write_cherry_pick_script(cfg, cache, outdir, 'relevant', 'cherry_pick_relevant.sh')
    assert path is None
    assert not os.path.exists(os.path.join(outdir, 'cherry_pick_relevant.sh'))


def test_write_scales_to_large_commit_set_quickly(tmp_path):
    """v19.4.1 regression guard: this must complete quickly even for a large
    commit set.  Before the fix this degenerated into O(N^2) file I/O and
    could look hung under strace for realistic prefilter_kept sizes."""
    import time
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    n = 2000
    many = [_commit('c%04d' % i) for i in range(n)]
    _write_cache(cache, 'prefilter_kept', many)
    _seed_db(cfg, {c['commit']: {'ok': True} for c in many})

    with patch('lib.cherrypick_script_gen.list_rev_commits',
              return_value=[c['commit'] for c in many]):
        t0 = time.time()
        path, stats = write_cherry_pick_script(
            cfg, cache, outdir, 'prefilter_kept', 'cherry_pick_prefiltered.sh')
        elapsed = time.time() - t0

    assert path is not None
    assert stats['cherry_pickable'] == n
    assert elapsed < 5.0, (
        'write_cherry_pick_script() took %.2fs for %d commits -- '
        'possible regression of the O(N^2) file-read bug' % (elapsed, n)
    )
