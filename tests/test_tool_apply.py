"""Real cherry-picks published to branches on disposable Git repositories (v21.7.0)."""
import pytest

from lib import tool_apply
from lib.tool_apply import ApplyError, apply, check_identity, resolve_destination
from lib.tool_check import plan
from tests.test_tool_check import git, repo, snapshot  # noqa: F401 (repo is a fixture)


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    for key, value in dict(GIT_COMMITTER_NAME='Applier', GIT_COMMITTER_EMAIL='applier@e.invalid',
                           GIT_AUTHOR_NAME='Applier', GIT_AUTHOR_EMAIL='applier@e.invalid',
                           GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null').items():
        monkeypatch.setenv(key, value)


def run(cfg, shas, dest, **kwargs):
    prepared = plan(cfg, shas, dest['base'])
    return apply(cfg, prepared, dest, **kwargs)


def subjects(path, rev):
    return git(path, 'log', '--reverse', '--format=%s', 'main..' + rev).split('\n')


def test_new_branch_is_published_in_order_with_identity_and_origin(repo):  # noqa: F811
    path, cfg, s = repo
    dest = resolve_destination(cfg, new_branch='backport', target='main')
    report = run(cfg, [s['b'], s['a'], s['c']], dest)
    assert report['published'] and report['state'] == 'published'
    assert report['counts']['applied'] == 3 and 'clean' not in report['counts']
    assert git(path, 'rev-parse', 'backport') == report['new_tip']
    assert subjects(path, 'backport') == ['a', 'b', 'c']
    assert git(path, 'log', '-1', '--format=%an|%cn', 'backport') == 'T|Applier'
    assert 'cherry picked from commit ' + s['c'] in git(path, 'log', '-1', '--format=%B', 'backport')
    assert [r['new_commit'] for r in report['results']][-1] == report['new_tip']


def test_origin_trailer_can_be_disabled(repo):  # noqa: F811
    path, cfg, s = repo
    dest = resolve_destination(cfg, new_branch='plain', target='main')
    run(cfg, [s['a']], dest, record_origin=False)
    assert 'cherry picked' not in git(path, 'log', '-1', '--format=%B', 'plain')


def test_working_tree_index_and_head_are_untouched(repo):  # noqa: F811
    path, cfg, s = repo
    (path / 'dirty.txt').write_text('keep')
    git(path, 'add', 'dirty.txt')
    (path / 'f.txt').write_text('local edit\n')
    before = snapshot(path)[:2] + snapshot(path)[3:]
    dest = resolve_destination(cfg, new_branch='backport', target='main')
    run(cfg, [s['a'], s['b']], dest)
    assert snapshot(path)[:2] + snapshot(path)[3:] == before
    assert (path / 'f.txt').read_text() == 'local edit\n'


def test_existing_branch_advances_from_its_tip(repo):  # noqa: F811
    path, cfg, s = repo
    git(path, 'branch', 'dest', 'main')
    dest = resolve_destination(cfg, branch='dest')
    assert dest['old_tip'] == s['base'] and dest['base'] == s['base']
    report = run(cfg, [s['a'], s['b']], dest)
    assert report['published'] and git(path, 'rev-parse', 'dest~2') == s['base']
    assert git(path, 'rev-parse', 'main') == s['base']


def test_complete_policy_blocks_publication_after_conflict(repo):  # noqa: F811
    path, cfg, s = repo
    dest = resolve_destination(cfg, new_branch='backport', target='main')
    report = run(cfg, [s['b'], s['bin']], dest, on_conflict='skip', publish_policy='complete')
    assert not report['published'] and report['state'] == 'blocked'
    assert report['counts']['conflict'] == 1 and report['counts']['applied'] == 1
    assert git(path, 'branch', '--list', 'backport') == ''


def test_applied_policy_publishes_only_what_applied(repo):  # noqa: F811
    path, cfg, s = repo
    dest = resolve_destination(cfg, new_branch='backport', target='main')
    report = run(cfg, [s['b'], s['bin']], dest, on_conflict='skip', publish_policy='applied')
    assert report['published'] and subjects(path, 'backport') == ['bin']


def test_stop_policy_leaves_remaining_not_tested(repo):  # noqa: F811
    path, cfg, s = repo
    dest = resolve_destination(cfg, new_branch='backport', target='main')
    report = run(cfg, [s['a'], s['b'], s['bin']], dest, on_conflict='stop', publish_policy='applied')
    assert [r['outcome'] for r in report['results']] == ['applied', 'applied', 'applied']
    dest = resolve_destination(cfg, new_branch='second', target='main')
    report = run(cfg, [s['b'], s['bin']], dest, on_conflict='stop', publish_policy='applied')
    assert [r['outcome'] for r in report['results']] == ['conflict', 'not_tested']
    assert not report['published'] and report['state'] == 'noop'


def test_merge_commit_blocks_complete_publication(repo):  # noqa: F811
    path, cfg, s = repo
    dest = resolve_destination(cfg, new_branch='backport', target='main')
    report = run(cfg, [s['bin'], s['merge']], dest)
    assert report['counts']['unsupported'] == 1 and not report['published']


@pytest.mark.parametrize('kwargs, message', [
    (dict(), 'exactly one'),
    (dict(branch='main', new_branch='x'), 'exactly one'),
    (dict(branch='main', target='main'), '--target'),
    (dict(branch='nope'), 'does not exist'),
    (dict(new_branch='main'), 'already exists'),
    (dict(new_branch='bad..name'), 'Invalid'),
    (dict(new_branch='-bad'), 'Invalid'),
    (dict(branch='main'), 'checked out'),
])
def test_destination_validation(repo, kwargs, message):  # noqa: F811
    path, cfg, s = repo
    with pytest.raises(ApplyError, match=message):
        resolve_destination(cfg, **kwargs)


def test_new_branch_requires_target(repo):  # noqa: F811
    path, cfg, s = repo
    with pytest.raises(ApplyError, match='--target'):
        resolve_destination(cfg, new_branch='x')
    assert resolve_destination(cfg, new_branch='x', default_rev='main')['base'] == s['base']


def test_branch_moved_during_run_is_not_overwritten(repo):  # noqa: F811
    path, cfg, s = repo
    git(path, 'branch', 'dest', 'main')
    dest = resolve_destination(cfg, branch='dest')
    moved = []

    def interfere(event):
        if not moved:
            git(path, 'update-ref', 'refs/heads/dest', s['a'])
            moved.append(True)

    report = run(cfg, [s['a'], s['b']], dest, progress=interfere)
    assert not report['published'] and report['state'] == 'failed'
    assert 'changed' in report['reason']
    assert git(path, 'rev-parse', 'dest') == s['a']


def test_interruption_cleans_up_and_publishes_nothing(repo):  # noqa: F811
    path, cfg, s = repo
    before = snapshot(path)

    def interrupt(event):
        raise KeyboardInterrupt

    dest = resolve_destination(cfg, new_branch='backport', target='main')
    with pytest.raises(KeyboardInterrupt):
        run(cfg, [s['a']], dest, progress=interrupt)
    assert snapshot(path) == before


def test_missing_identity_is_reported(repo, monkeypatch):  # noqa: F811
    path, cfg, s = repo
    monkeypatch.setattr(tool_apply.tc, 'git', lambda *a, **k: (128, b'', b'no identity'))
    with pytest.raises(ApplyError, match='identity'):
        check_identity(cfg)


def test_commit_already_in_target_does_not_crash(repo):  # noqa: F811
    path, cfg, s = repo
    dest = resolve_destination(cfg, new_branch='backport', target='main')
    report = run(cfg, [s['base']], dest)
    assert report['results'][0]['in_target'] is True
    assert report['results'][0]['outcome'] in ('no_change', 'conflict')
    assert not report['published']
