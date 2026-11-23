"""`kcommit_tool.py check`: selection, options, reports and dry-run (v21.7.0)."""
import json

import pytest

from lib.commands.cmd_tool import main, parser
from lib.commit_sets import FILES
from tests.test_tool_check import git, repo, snapshot  # noqa: F401 (repo is a fixture)


@pytest.fixture
def project(repo, tmp_path, monkeypatch):  # noqa: F811
    path, cfg, shas = repo
    names = ['a', 'b', 'c', 'bin']
    rows = [dict(commit=shas[n], subject='subject ' + n, score=10 * i) for i, n in enumerate(names, 1)]
    cache, output = tmp_path / 'cache', tmp_path / 'output'
    cache.mkdir()
    output.mkdir()
    for name, values in dict(all=rows, related=rows, scored=rows, relevant=rows, below_threshold=[]).items():
        (cache / FILES[name]).write_text(json.dumps(values))
    (cache / 'filtered_commits.json').write_text('[]')
    (output / 'relevant_commits.json').write_text(json.dumps(rows))
    config = tmp_path / 'project.json'
    config.write_text(json.dumps({'paths': {'cache_dir': str(cache), 'output_dir': str(output)},
                                  'kernel': {'source_dir': str(path), 'rev_old': 'main'}}))
    import lib.ai_import_store
    monkeypatch.setattr(lib.ai_import_store, 'load_report_results', lambda _: {})
    return config, path, shas


def invoke(project, *args):
    return main(['--config', str(project[0]), '--format', 'json', *args])


def test_default_series_check_uses_configured_target(project, capsys):
    config, path, shas = project
    assert invoke(project, 'check') == 0
    report = json.loads(capsys.readouterr().out)
    assert report['target'] == git(path, 'rev-parse', 'main') and report['target_requested'] == 'main'
    assert [r['commit'] for r in report['results']] == [shas[n] for n in ('a', 'b', 'c', 'bin')]
    assert report['summary']['clean'] == 4 and report['execution_complete'] is True


@pytest.mark.parametrize('method', ['index', 'cherry-pick'])
def test_individual_mode_reports_dependency_conflict(project, capsys, method):
    config, path, shas = project
    assert invoke(project, 'check', '--mode', 'individual', '--method', method, '--target', 'main') == 0
    report = json.loads(capsys.readouterr().out)
    assert report['summary']['conflict'] == 1 and report['summary']['clean'] == 3
    assert next(r for r in report['results'] if r['commit'] == shas['b'])['outcome'] == 'conflict'


def test_stop_policy_marks_remaining_not_tested(project, capsys):
    config, path, shas = project
    assert invoke(project, 'check', '--mode', 'individual', '--on-conflict', 'stop') == 0
    report = json.loads(capsys.readouterr().out)
    assert report['summary']['not_tested'] == 2 and report['stopped'] is True


def test_dry_run_attempts_nothing_and_leaves_repository_unchanged(project, capsys):
    config, path, shas = project
    before = snapshot(path)
    assert invoke(project, 'check', '--dry-run') == 0
    report = json.loads(capsys.readouterr().out)
    assert report['dry_run'] is True and report['summary'] is None and report['execution_complete'] is None
    assert [r['planned'] for r in report['results']] == ['attempt'] * 4
    assert snapshot(path) == before


def test_bad_target_fails_without_primary_output(project, capsys):
    assert invoke(project, 'check', '--target', 'no-such-revision') == 1
    captured = capsys.readouterr()
    assert captured.out == '' and 'Error:' in captured.err


def test_raw_and_text_formats(project, capsys):
    config, path, shas = project
    assert main(['--config', str(config), '--format', 'raw', 'check']) == 0
    assert capsys.readouterr().out.split() == [shas[n] for n in ('a', 'b', 'c', 'bin')]
    assert main(['--config', str(config), 'check', '--dry-run']) == 0
    text = capsys.readouterr().out
    assert 'Target: main' in text and '[dry run]' in text


def test_check_options_are_command_specific(project):
    config = str(project[0])
    for args in (['list', '--mode', 'series'], ['summary', '--dry-run'], ['show', 'x', '--method', 'index']):
        with pytest.raises(SystemExit):
            parser().parse_args(['--config', config, *args])
