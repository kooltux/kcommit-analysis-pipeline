"""Isolated commit-application simulations on disposable Git repositories (v21.7.0)."""
import os
import shutil
import subprocess

import pytest

from lib.tool_check import CheckError, execute, plan

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='git is required')
ENV = dict(GIT_AUTHOR_NAME='T', GIT_AUTHOR_EMAIL='t@e.invalid', GIT_COMMITTER_NAME='T',
           GIT_COMMITTER_EMAIL='t@e.invalid', GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null')


def git(path, *args, data=None):
    env = dict(os.environ)
    env.update(ENV)
    done = subprocess.run(['git', '-C', str(path), *args], input=data, capture_output=True, env=env, check=True)
    return done.stdout.decode().strip()


def commit(path, name, lines=None, message=None, binary=None):
    if lines is not None:
        (path / 'f.txt').write_text(''.join(line + '\n' for line in lines))
    if binary is not None:
        (path / 'b.bin').write_bytes(binary)
    git(path, 'add', '-A')
    git(path, 'commit', '-q', '-m', message or name)
    return git(path, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / 'repo'
    path.mkdir()
    git(path, 'init', '-q', '-b', 'main')
    base_lines = ['line %d' % n for n in range(1, 11)]
    shas = {'base': commit(path, 'base', base_lines, binary=b'\0\1\2')}
    git(path, 'checkout', '-q', '-b', 'feature')
    a = list(base_lines); a[4] = 'A five'
    shas['a'] = commit(path, 'a', a)
    b = list(a); b[4] = 'B five'
    shas['b'] = commit(path, 'b', b)
    shas['c'] = commit(path, 'c', b + ['tail'])
    shas['bin'] = commit(path, 'bin', binary=b'\0\3\4\5')
    git(path, 'commit', '-q', '--allow-empty', '-m', 'empty')
    shas['empty'] = git(path, 'rev-parse', 'HEAD')
    git(path, 'checkout', '-q', 'main')
    git(path, 'checkout', '-q', '-b', 'side', shas['base'])
    shas['side'] = commit(path, 'side', ['side'] + base_lines[1:])
    git(path, 'checkout', '-q', 'feature')
    git(path, 'merge', '-q', '--no-ff', '-m', 'merge', 'side')
    shas['merge'] = git(path, 'rev-parse', 'HEAD')
    git(path, 'checkout', '-q', 'main')
    cfg = {'kernel': {'source_dir': str(path)}}
    return path, cfg, shas


def run(cfg, shas, **kwargs):
    prepared = plan(cfg, shas, kwargs.pop('target', 'main'))
    return execute(cfg, prepared, **kwargs)


def outcomes(report):
    return {row['commit']: row['outcome'] for row in report['results']}


def snapshot(path):
    return (git(path, 'rev-parse', 'HEAD'), git(path, 'status', '--porcelain'), git(path, 'branch', '--list'),
            git(path, 'worktree', 'list').count('\n'), git(path, 'ls-files', '-s'))


METHODS = ['index', 'cherry-pick']


@pytest.mark.parametrize('method', METHODS)
def test_dependent_pair_fails_individually_but_succeeds_in_series(repo, method):
    path, cfg, s = repo
    individual = run(cfg, [s['b']], mode='individual', method=method)
    assert outcomes(individual)[s['b']] == 'conflict'
    assert individual['results'][0]['conflict_count'] in (None, 1)
    series = run(cfg, [s['b'], s['a']], mode='series', method=method)
    assert [r['commit'] for r in series['results']] == [s['a'], s['b']]
    assert set(outcomes(series).values()) == {'clean'}


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('mode', ['individual', 'series'])
def test_conflict_is_recovered_and_later_commits_still_run(repo, method, mode):
    path, cfg, s = repo
    report = run(cfg, [s['b'], s['c'], s['bin']], mode=mode, method=method, on_conflict='skip')
    assert outcomes(report) == {s['b']: 'conflict', s['c']: 'clean', s['bin']: 'clean'}
    first = report['results'][0]
    assert first['recovery'] in ('verified', 'reset') and first['conflict_count'] == 1
    assert first['conflicts'] == ['f.txt']
    assert report['execution_complete'] and not report['stopped']


@pytest.mark.parametrize('method', METHODS)
def test_stop_marks_remaining_not_tested(repo, method):
    path, cfg, s = repo
    report = run(cfg, [s['b'], s['bin']], mode='series', method=method, on_conflict='stop')
    assert [r['outcome'] for r in report['results']] == ['conflict', 'not_tested']
    assert report['counts']['not_tested'] == 1 and report['stopped'] and report['execution_complete']


@pytest.mark.parametrize('method', METHODS)
def test_ordering_ancestor_first_without_adding_unselected(repo, method):
    path, cfg, s = repo
    prepared = plan(cfg, [s['c'], s['a']], 'main')
    assert [e['commit'] for e in prepared['entries']] == [s['a'], s['c']]
    report = execute(cfg, prepared, mode='individual', method=method)
    assert s['b'] not in outcomes(report)
    assert outcomes(report)[s['a']] == 'clean'


@pytest.mark.parametrize('method', METHODS)
def test_binary_empty_and_merge_handling(repo, method):
    path, cfg, s = repo
    report = run(cfg, [s['bin'], s['empty'], s['merge']], mode='individual', method=method)
    found = outcomes(report)
    assert found[s['bin']] == 'clean'
    assert found[s['empty']] == 'no_change'
    assert found[s['merge']] == 'unsupported'


@pytest.mark.parametrize('method', METHODS)
def test_missing_object_does_not_stop_valid_work(repo, method):
    path, cfg, s = repo
    report = run(cfg, ['f' * 40, s['bin']], method=method)
    assert outcomes(report)['f' * 40] == 'error'
    assert outcomes(report)[s['bin']] == 'clean'
    assert report['execution_complete'] is True


@pytest.mark.parametrize('method', METHODS)
@pytest.mark.parametrize('mode', ['individual', 'series'])
def test_user_repository_is_unchanged(repo, method, mode):
    path, cfg, s = repo
    (path / 'dirty.txt').write_text('keep')
    git(path, 'add', 'dirty.txt')
    (path / 'f.txt').write_text('local edit\n')
    before = snapshot(path)
    run(cfg, [s['a'], s['b'], s['bin']], mode=mode, method=method)
    assert snapshot(path) == before
    assert (path / 'f.txt').read_text() == 'local edit\n'


def test_bad_target_is_reported(repo):
    path, cfg, s = repo
    with pytest.raises(CheckError):
        plan(cfg, [s['a']], 'no-such-revision')
