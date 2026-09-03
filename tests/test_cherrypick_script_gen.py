"""Tests for lib.cherrypick_script_gen -- v19.5.0: static script asset copy
+ JSON data generation."""
import os
import json
import stat
import subprocess
import filecmp
from unittest.mock import patch

import pytest

from lib.cherrypick_script_gen import (
    write_cherry_pick_files,
    _load_commits, _index_shas_and_subjects,
    _ASSET_SCRIPT_PATH,
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


# ── _index_shas_and_subjects ──────────────────────────────────

def test_index_shas_and_subjects_dedup_preserves_first_order():
    commits = [
        {'commit': 'aaa', 'subject': 's1'},
        {'commit': 'bbb', 'subject': 's2'},
        {'commit': 'aaa', 'subject': 's1-dup'},
        {'commit': 'ccc', 'subject': 's3'},
    ]
    shas, subjects = _index_shas_and_subjects(commits)
    assert shas == ['aaa', 'bbb', 'ccc']
    assert subjects['aaa'] == 's1'
    assert subjects['ccc'] == 's3'


def test_index_shas_and_subjects_skips_entries_without_sha():
    commits = [{'commit': 'a', 'subject': 'x'}, {'subject': 'no-sha'}, {}]
    shas, subjects = _index_shas_and_subjects(commits)
    assert shas == ['a']


# ── static asset: existence and shape ─────────────────────────────────

def test_static_asset_script_exists():
    """v19.5.0: cherry_pick.sh is a static asset shipped under configs/assets/."""
    assert os.path.exists(_ASSET_SCRIPT_PATH), (
        'Static asset not found: %s' % _ASSET_SCRIPT_PATH
    )


def test_static_asset_script_is_valid_bash():
    """The static asset must be syntactically valid bash (bash -n)."""
    result = subprocess.run(
        ['bash', '-n', _ASSET_SCRIPT_PATH],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_static_asset_script_has_no_run_specific_placeholders():
    """The static asset must be fully generic: no template placeholders,
    no hardcoded commit counts or revisions."""
    with open(_ASSET_SCRIPT_PATH) as f:
        content = f.read()
    assert 'usage()' in content
    assert 'getopt' in content
    assert '--set' in content


# ── write_cherry_pick_files: basic functionality ──────────────────────────

def test_write_copies_static_script_and_writes_data_file(tmp_path):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a')])
    _seed_db(cfg, {'a': {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a']):
        script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)

    assert script_path is not None
    assert data_path is not None
    assert os.path.exists(script_path)
    assert os.path.exists(data_path)

    # v19.5.0: script is copied byte-for-byte from the static asset
    assert filecmp.cmp(script_path, _ASSET_SCRIPT_PATH, shallow=False), (
        'cherry_pick.sh must be an exact copy of the static asset'
    )

    # Check script is executable
    mode = os.stat(script_path).st_mode
    assert mode & stat.S_IXUSR

    # Check data file structure
    with open(data_path) as f:
        data = json.load(f)
    assert 'commits' in data
    assert len(data['commits']) == 1
    assert data['commits'][0]['sha'] == 'a'
    assert data['commits'][0]['relevant'] == True
    # v19.5.0: target_rev/rev_new embedded so script is self-contained
    assert data['target_rev'] == 'v6.1'
    assert data['rev_new'] == 'v6.6'


def test_write_returns_none_when_nothing_cherry_pickable(tmp_path):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [])

    script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)

    assert script_path is None
    assert data_path is None
    assert stats['cherry_pickable'] == 0
    # No files should be written to outdir at all
    assert not os.path.exists(os.path.join(outdir, 'cherry_pick.sh'))
    assert not os.path.exists(os.path.join(outdir, 'cherry_pick_data.json'))


# ── write_cherry_pick_files: relevant flag ─────────────────────────────

def test_write_marks_relevant_commits_correctly(tmp_path):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)

    _write_cache(cache, 'prefilter_kept', [
        _commit('a', 'commit a'),
        _commit('b', 'commit b'),
        _commit('c', 'commit c'),
    ])
    _write_cache(cache, 'relevant', [
        _commit('a', 'commit a'),
        _commit('c', 'commit c'),
    ])

    _seed_db(cfg, {'a': {'ok': True}, 'b': {'ok': True}, 'c': {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a', 'b', 'c']):
        script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)

    assert script_path is not None
    assert data_path is not None

    with open(data_path) as f:
        data = json.load(f)

    commits_by_sha = {c['sha']: c for c in data['commits']}
    assert commits_by_sha['a']['relevant'] == True
    assert commits_by_sha['b']['relevant'] == False
    assert commits_by_sha['c']['relevant'] == True

    assert stats['relevant_count'] == 2
    assert stats['prefiltered_count'] == 1


# ── write_cherry_pick_files: git-history order ─────────────────────────────

def test_write_orders_by_git_history_not_cache_order(tmp_path):
    """Commits must be in git-history order, not cache file order."""
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)

    _write_cache(cache, 'relevant', [
        _commit('c3'),
        _commit('c2'),
        _commit('c1'),
    ])
    _seed_db(cfg, {'c1': {'ok': True}, 'c2': {'ok': True}, 'c3': {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['c1', 'c2', 'c3']):
        script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)

    assert data_path is not None
    with open(data_path) as f:
        data = json.load(f)

    shas = [c['sha'] for c in data['commits']]
    assert shas == ['c1', 'c2', 'c3']


# ── write_cherry_pick_files: filtering ─────────────────────────────────

def test_write_only_includes_ok_true_commits(tmp_path):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [
        _commit('good'),
        _commit('bad'),
        _commit('untested'),
    ])
    _seed_db(cfg, {'good': {'ok': True}, 'bad': {'ok': False}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['good', 'bad', 'untested']):
        script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)

    assert data_path is not None
    with open(data_path) as f:
        data = json.load(f)

    shas = [c['sha'] for c in data['commits']]
    assert shas == ['good']
    assert stats['cherry_pickable'] == 1
    assert stats['tested'] == 2
    assert stats['skipped_conflict'] == 1
    assert stats['skipped_untested'] == 1


# ── write_cherry_pick_files: edge cases ────────────────────────────────

def test_write_handles_missing_cherry_db(tmp_path):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a')])

    script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)

    assert script_path is None
    assert data_path is None
    assert stats['skipped_untested'] == 1


def test_write_scales_to_large_commit_set_quickly(tmp_path):
    """v19.4.1 regression guard: must complete quickly for large commit sets."""
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
        script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)
        elapsed = time.time() - t0

    assert script_path is not None
    assert data_path is not None
    assert stats['cherry_pickable'] == n
    assert elapsed < 5.0, (
        'write_cherry_pick_files() took %.2fs for %d commits -- '
        'possible regression of the O(N^2) file-read bug' % (elapsed, n)
    )


# ── end-to-end: real script execution against real data ─────────────────────

def test_copied_script_help_reports_dynamic_counts(tmp_path):
    """v19.5.0: --help / usage() must compute counts from cherry_pick_data.json
    dynamically, never hardcode them."""
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'prefilter_kept', [_commit('a'), _commit('b')])
    _write_cache(cache, 'relevant', [_commit('a')])
    _seed_db(cfg, {'a': {'ok': True}, 'b': {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a', 'b']):
        script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)

    result = subprocess.run(
        [script_path, '--help'],
        capture_output=True, text=True, timeout=15, cwd=outdir,
    )
    assert result.returncode == 0, result.stderr
    assert 'Total commits:    2' in result.stdout
    assert 'Relevant:         1' in result.stdout


def test_copied_script_no_args_shows_usage_and_error(tmp_path):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a')])
    _seed_db(cfg, {'a': {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a']):
        script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)

    result = subprocess.run(
        [script_path],
        capture_output=True, text=True, timeout=15, cwd=outdir,
    )
    assert '--set argument is required' in result.stderr
    assert 'Usage: cherry_pick.sh' in result.stdout


def test_copied_script_invalid_set_shows_usage(tmp_path):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    cfg = _cfg(tmp_path)
    _write_cache(cache, 'relevant', [_commit('a')])
    _seed_db(cfg, {'a': {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a']):
        script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)

    result = subprocess.run(
        [script_path, '--set=bogus'],
        capture_output=True, text=True, timeout=15, cwd=outdir,
    )
    assert '--set must be' in result.stderr


def test_copied_script_full_cherry_pick_run_with_special_characters(tmp_path):
    """v19.5.0 regression guard: subjects containing quotes/parens must
    survive the JSON -> heredoc -> Python round trip unharmed, and the
    real git cherry-pick must succeed end to end."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.email', 'a@b.c'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repo, check=True)

    (repo / 'f.txt').write_text('base\n')
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', 'base'], cwd=repo, check=True)
    base_rev = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo,
                              capture_output=True, text=True).stdout.strip()

    subprocess.run(['git', 'checkout', '-q', '-b', 'feature'], cwd=repo, check=True)
    tricky_subject = 'fix: something (with) "quotes" and \'ticks\''
    (repo / 'a.txt').write_text('a\n')
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', tricky_subject], cwd=repo, check=True)
    sha1 = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    subprocess.run(['git', 'checkout', '-q', base_rev], cwd=repo, check=True)

    outdir = tmp_path / 'output'
    outdir.mkdir()
    import shutil
    shutil.copyfile(_ASSET_SCRIPT_PATH, outdir / 'cherry_pick.sh')
    os.chmod(outdir / 'cherry_pick.sh', 0o755)
    with open(outdir / 'cherry_pick_data.json', 'w') as f:
        json.dump({
            'target_rev': base_rev,
            'rev_new': sha1,
            'commits': [{'sha': sha1, 'subject': tricky_subject, 'relevant': True}],
        }, f)

    result = subprocess.run(
        [str(outdir / 'cherry_pick.sh'), '--set=relevant', '--git-dir', str(repo)],
        capture_output=True, text=True, timeout=20, input='n\n', cwd=outdir,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '1 commits to cherry-pick' in result.stdout
    assert 'OK' in result.stdout

    head_sha = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo,
                              capture_output=True, text=True).stdout.strip()
    log = subprocess.run(['git', 'log', '-1', '--format=%s'], cwd=repo,
                         capture_output=True, text=True).stdout.strip()
    assert log == tricky_subject
    assert head_sha != base_rev


# ── paths.assets_dir override (v19.5.0) ────────────────────────────

def test_asset_script_path_defaults_to_shipped_configs_assets(tmp_path):
    """When cfg has no 'paths' key (or no assets_dir), the shipped default
    configs/assets/cherry_pick.sh is used."""
    from lib.cherrypick_script_gen import _resolve_asset_script_path
    cfg = _cfg(tmp_path)
    assert _resolve_asset_script_path(cfg) == _ASSET_SCRIPT_PATH


def test_asset_script_path_honors_paths_assets_dir_override(tmp_path):
    """A cfg with paths.assets_dir set (as populated by lib.config.load_config()
    from a product config's "paths": {"assets_dir": ...}) must use that
    directory's cherry_pick.sh instead of the shipped default."""
    from lib.cherrypick_script_gen import _resolve_asset_script_path
    custom_dir = tmp_path / 'custom_assets'
    custom_dir.mkdir()
    (custom_dir / 'cherry_pick.sh').write_text('#!/usr/bin/env bash\necho custom\n')

    cfg = _cfg(tmp_path)
    cfg['paths'] = {'assets_dir': str(custom_dir)}

    resolved = _resolve_asset_script_path(cfg)
    assert resolved == str(custom_dir / 'cherry_pick.sh')


def test_write_copies_custom_asset_when_paths_assets_dir_overridden(tmp_path):
    """v19.5.0 end-to-end: write_cherry_pick_files() copies the product
    config's own cherry_pick.sh (via paths.assets_dir), not the shipped one."""
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)

    custom_dir = tmp_path / 'custom_assets'
    custom_dir.mkdir()
    custom_script = custom_dir / 'cherry_pick.sh'
    custom_script.write_text('#!/usr/bin/env bash\necho "this is the custom script"\n')

    cfg = _cfg(tmp_path)
    cfg['paths'] = {'assets_dir': str(custom_dir)}
    _write_cache(cache, 'relevant', [_commit('a')])
    _seed_db(cfg, {'a': {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=['a']):
        script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)

    assert script_path is not None
    assert filecmp.cmp(script_path, str(custom_script), shallow=False), (
        'cherry_pick.sh must be copied from the overridden paths.assets_dir'
    )
    assert not filecmp.cmp(script_path, _ASSET_SCRIPT_PATH, shallow=False), (
        'copied script should NOT match the shipped default once overridden'
    )
