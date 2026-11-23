"""Companion CLI selection, validation and Git regressions (v21.7.0)."""
import csv
import io
import json
import subprocess

import pytest

from lib.commands.cmd_tool import main, parser
from lib.commit_sets import FILES, read_sets, read_sets_from_dirs
from lib.tool_output import render
from lib.tool_query import Predicates, QueryError, present, validate

SHAS = [format(n, '040x') for n in (1, 2, 3)]


@pytest.fixture
def project(tmp_path, monkeypatch):
    cache, output = tmp_path / 'cache', tmp_path / 'output'
    cache.mkdir()
    output.mkdir()
    rows = [dict(commit=sha, subject='subject ' + str(n), score=n * 10,
                 files=['net/a.c'], scoring={'trace': {'nested': [n]}})
            for n, sha in enumerate(SHAS, 1)]
    for name, values in dict(all=rows, related=rows, scored=rows,
                              relevant=rows[1:], below_threshold=rows[:1]).items():
        (cache / FILES[name]).write_text(json.dumps(values), encoding='utf-8')
    (cache / 'filtered_commits.json').write_text('[]')
    (output / 'relevant_commits.json').write_text(json.dumps(rows[1:2]))
    config = tmp_path / 'project.json'
    config.write_text(json.dumps({'paths': {'cache_dir': str(cache), 'output_dir': str(output)},
                                  'kernel': {'source_dir': str(tmp_path)}}))
    import lib.ai_import_store
    monkeypatch.setattr(lib.ai_import_store, 'load_report_results', lambda _: {SHAS[0]: {'specialist': {'keep': True}}})
    return config, cache, output


def invoke(project, *args):
    return main(['--config', str(project[0]), '--format', 'json', *args])


def test_nested_records_and_ai_do_not_mutate_artifacts(project, capsys):
    before = {p: p.read_bytes() for root in project[1:] for p in root.rglob('*') if p.is_file()}
    assert invoke(project, 'list', '--where', 'score >= `20`') == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r['commit'] for r in rows] == SHAS[1:]
    assert rows[0]['scoring']['trace']['nested'] == [2]
    assert rows[0]['sets']['displayed'] is True
    assert invoke(project, 'show', SHAS[0]) == 0
    assert json.loads(capsys.readouterr().out)[0]['ai']['specialist']['keep'] is True
    assert before == {p: p.read_bytes() for root in project[1:] for p in root.rglob('*') if p.is_file()}


def test_manual_intersection_and_direct_candidates(project, capsys):
    path = project[0].parent / 'manual.txt'
    path.write_text(SHAS[1] + '\n' + SHAS[1] + ' optional subject\n# comment\n')
    assert invoke(project, 'list', '--list', 'manual=' + str(path), '--where', 'lists.manual') == 0
    assert [r['commit'] for r in json.loads(capsys.readouterr().out)] == SHAS[1:2]
    assert invoke(project, 'list', '--commits-file', str(path)) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    assert invoke(project, 'list', 'related', '--commits-file', str(path)) == 1
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('text', ['score', 'files', '`1`', "'yes'", 'score >'])
def test_invalid_predicate_has_no_partial_stdout(project, capsys, text):
    assert invoke(project, 'list', '--where', text) == 2
    assert capsys.readouterr().out == ''


def test_validation_sample_null_and_type_error(project, capsys):
    assert invoke(project, 'validate-filter', '--where', 'missing', '--sample', '2', '--explain', '--limit', '1') == 0
    report = json.loads(capsys.readouterr().out)
    assert report['null'] == 2 and len(report['explanations']) == 1
    assert report['evaluated'] == 2 and not report['evaluation_complete']
    assert invoke(project, 'validate-filter', '--where', 'score') == 2
    assert 'boolean or null' in json.loads(capsys.readouterr().out)['first_error']['error']
    assert validate([], Predicates(['score >= `20`']))['evaluation'] == 'not_run'


def test_filter_file_fields_sort_and_projection(project, capsys):
    path = project[0].parent / 'predicate.jmespath'
    path.write_text('score >=\n`20`')
    assert invoke(project, 'list', '--filter-file', str(path), '--sort', 'score', '--reverse', '--limit', '1', '--project', '{sha: commit}') == 0
    assert json.loads(capsys.readouterr().out) == [{'sha': SHAS[-1]}]
    assert invoke(project, 'fields') == 0
    assert 'scoring.trace.nested[]' in {r['path'] for r in json.loads(capsys.readouterr().out)}
    assert present([{'x': None}, {'x': 1}, {'x': 2}], 'x', True) == [{'x': 2}, {'x': 1}, {'x': None}]
    with pytest.raises(QueryError):
        present([{'x': 1}, {'x': 'a'}], 'x')


def test_loader_preserves_standalone_contract_and_unavailability(project, capsys):
    config, cache, output = project
    loaded = {}
    values = read_sets_from_dirs(str(cache), str(output), loaded)
    assert loaded['all'][0]['commit'] == SHAS[0]
    (output / 'scripts').mkdir()
    (output / 'pipeline_config.json').write_text(config.read_text())
    assert read_sets(str(output / 'scripts/list_commits.py'))[1:] == values
    (cache / FILES['relevant']).unlink()
    assert invoke(project, 'sets') == 0
    rows = json.loads(capsys.readouterr().out)
    assert next(r for r in rows if r['name'] == 'relevant')['count'] is None
    assert invoke(project, 'list', 'relevant') == 1
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('fmt', ['text', 'raw', 'csv', 'json', 'markdown'])
def test_renderers(fmt):
    text = render([{'name': 'a|b', 'nested': {'values': [1, 2]}, 'note': 'a\nb'}], fmt)
    assert 'values' in text
    if fmt == 'csv':
        assert len(list(csv.reader(io.StringIO(text)))) == 2
    if fmt == 'markdown':
        assert 'a\\|b' in text and '<br>' in text


def test_options_and_output_are_safe(project, capsys):
    with pytest.raises(SystemExit):
        parser().parse_args(['--config', str(project[0]), 'summary', '--where', '`true`'])
    capsys.readouterr()
    path = project[0].parent / 'report.json'
    args = ['--config', str(project[0]), '--output', str(path), 'summary']
    assert main(args) == 0
    original = path.read_bytes()
    assert main(args) == 1 and path.read_bytes() == original


def test_real_git_branch_query(tmp_path, capsys):
    def git(*args):
        return subprocess.run(['git', '-C', str(tmp_path), *args], check=True, capture_output=True, text=True)
    git('init')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-m', 'root')
    git('branch', 'candidate')
    config = tmp_path / 'project.json'
    config.write_text(json.dumps({'kernel': {'source_dir': str(tmp_path)}}))
    assert main(['--config', str(config), '--format', 'json', 'branches', '--where', "name == 'candidate'"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1 and rows[0]['name'] == 'candidate'
