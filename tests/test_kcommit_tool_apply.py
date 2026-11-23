"""`kcommit_tool.py apply`: destinations, policies, reports and exit codes (v21.7.0)."""
import json

import pytest

from lib.commands.cmd_tool import main, parser
from tests.test_kcommit_tool_check import project  # noqa: F401 (fixture)
from tests.test_tool_check import git, repo, snapshot  # noqa: F401 (fixture)


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    for key, value in dict(GIT_COMMITTER_NAME='Applier', GIT_COMMITTER_EMAIL='applier@e.invalid',
                           GIT_AUTHOR_NAME='Applier', GIT_AUTHOR_EMAIL='applier@e.invalid',
                           GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null').items():
        monkeypatch.setenv(key, value)


def invoke(project, *args):  # noqa: F811
    return main(['--config', str(project[0]), '--format', 'json', *args])


def test_new_branch_is_published(project, capsys):  # noqa: F811
    config, path, shas = project
    assert invoke(project, 'apply', '--new-branch', 'bk', '--target', 'main') == 0
    report = json.loads(capsys.readouterr().out)
    assert report['published'] is True and report['state'] == 'published'
    assert report['summary']['applied'] == 4
    assert [r['outcome'] for r in report['results']] == ['applied'] * 4
    assert git(path, 'rev-parse', 'bk') == report['new_tip']
    assert report['destination']['kind'] == 'new'


def test_default_target_comes_from_configuration(project, capsys):  # noqa: F811
    config, path, shas = project
    assert invoke(project, 'apply', '--new-branch', 'bk') == 0
    assert json.loads(capsys.readouterr().out)['destination']['base'] == git(path, 'rev-parse', 'main')


def test_dry_run_changes_nothing(project, capsys):  # noqa: F811
    config, path, shas = project
    before = snapshot(path)
    assert invoke(project, 'apply', '--new-branch', 'bk', '--dry-run') == 0
    report = json.loads(capsys.readouterr().out)
    assert report['state'] == 'dry_run' and report['published'] is False
    assert [r['planned'] for r in report['results']] == ['attempt'] * 4
    assert snapshot(path) == before and git(path, 'branch', '--list', 'bk') == ''


@pytest.mark.parametrize('args', [
    [], ['--branch', 'main', '--new-branch', 'x'], ['--branch', 'feature', '--target', 'main'],
    ['--branch', 'missing'], ['--new-branch', 'main'],
])
def test_invalid_destinations_fail_without_primary_output(project, capsys, args):  # noqa: F811
    assert invoke(project, 'apply', *args) == 1
    captured = capsys.readouterr()
    assert captured.out == '' and 'Error:' in captured.err


def test_blocked_by_policy_returns_three_and_publishes_nothing(project, capsys):  # noqa: F811
    config, path, shas = project
    picks = config.parent / 'picks.txt'
    picks.write_text(shas['b'] + '\n')
    assert invoke(project, 'apply', '--commits-file', str(picks), '--new-branch', 'bk', '--target', 'main') == 3
    report = json.loads(capsys.readouterr().out)
    assert report['state'] == 'blocked' and report['published'] is False
    assert git(path, 'branch', '--list', 'bk') == ''


def test_raw_and_text_formats(project, capsys):  # noqa: F811
    config, path, shas = project
    assert main(['--config', str(config), '--format', 'raw', 'apply', '--new-branch', 'bk', '--target', 'main']) == 0
    assert capsys.readouterr().out.split() == [shas[n] for n in ('a', 'b', 'c', 'bin')]
    assert main(['--config', str(config), 'apply', '--new-branch', 'again', '--dry-run']) == 0
    text = capsys.readouterr().out
    assert 'Destination: new branch again' in text and 'Published: no (dry run)' in text


def test_apply_options_are_command_specific(project):  # noqa: F811
    config = str(project[0])
    for args in (['check', '--publish', 'complete'], ['list', '--branch', 'x'], ['check', '--new-branch', 'x']):
        with pytest.raises(SystemExit):
            parser().parse_args(['--config', config, *args])
