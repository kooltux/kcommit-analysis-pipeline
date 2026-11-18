"""Tree rendering and CLI listing regressions, independent of pipeline imports."""
import importlib.util
from pathlib import Path
import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'lib/commit_sets.py'
spec = importlib.util.spec_from_file_location('commit_tree_tool', SOURCE)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


def example():
    return dict(all={1, 2, 3, 4, 5}, related={2, 3, 4, 5},
                scored={2, 3, 4, 5}, relevant={2, 3},
                prefilter_rejected={1}, below_threshold={4, 5},
                filtered={4, 5}, displayed={2, 3})


def rows(sets):
    return [line.split() for line in tool.tree_lines(sets)]


def test_complete_tree_omits_redundant_numeric_rows():
    lines = rows(example())
    numeric = [line for line in lines if line and line[-1].isdigit()]
    assert [line[-2:] for line in numeric] == [
        ['all', '5'], ['prefilter_rejected', '1'], ['related', '4'],
        ['below_threshold', '2'], ['relevant', '2']]
    text = '\n'.join(tool.tree_lines(example()))
    assert 'Scoring complete: scored = related' in text
    assert 'Report complete: displayed = relevant' in text
    assert '├── prefilter_rejected' in text
    assert '└── related' in text
    assert 'filtered' not in text


def test_partial_scoring_and_top_n_have_explicit_partition_branches():
    sets = example()
    sets['scored'] = {2, 3, 4}
    sets['below_threshold'] = {4}
    sets['displayed'] = {2}
    numeric = [line[-2:] for line in rows(sets) if line and line[-1].isdigit()]
    assert numeric == [['all', '5'], ['prefilter_rejected', '1'],
        ['related', '4'], ['unscored', '1'], ['scored', '3'],
        ['below_threshold', '1'], ['relevant', '2'],
        ['not_displayed', '1'], ['displayed', '1']]
    assert 'complete:' not in '\n'.join(tool.tree_lines(sets))


@pytest.mark.parametrize('name', ['all', 'related', 'scored', 'relevant', 'displayed'])
def test_missing_inputs_are_not_claimed_empty_or_complete(name):
    sets = example()
    del sets[name]
    text = '\n'.join(tool.tree_lines(sets))
    if name in ('all', 'related', 'relevant'):
        assert any(line and line[-2:] == [name, 'unavailable'] for line in rows(sets))
    if name in ('related', 'scored'):
        assert 'Scoring coverage: unavailable' in text
    if name in ('relevant', 'displayed'):
        assert 'Report coverage: unavailable' in text


def test_all_empty_sets_are_valid_and_equal():
    text = '\n'.join(tool.tree_lines(dict.fromkeys(tool.NAMES, set())))
    numeric = [line for line in text.splitlines() if line.split() and line.split()[-1] == '0']
    assert len(numeric) == 5 and 'unavailable' not in text
    assert 'Scoring complete:' in text and 'Report complete:' in text


@pytest.mark.parametrize('child,parent', [('scored','related'), ('displayed','relevant')])
def test_equality_checks_membership_not_only_counts(child,parent):
    sets = example()
    sets[child] = set(range(10, 10 + len(sets[parent])))
    text = '\n'.join(tool.tree_lines(sets))
    assert child + ' = ' + parent not in text
    assert 'inconsistent' in text


@pytest.mark.parametrize('args', [[], ['--sets'], ['-h'], ['--help']])
def test_cli_tree_and_help_share_presentation(monkeypatch,capsys,args):
    monkeypatch.setattr(tool, 'read_sets', lambda path: ({}, example(), {}, []))
    assert tool.main(args, script_path='unused') == 0
    output = capsys.readouterr()
    assert output.err == '' and 'Commit sets:' in output.out
    assert ('Usage:' in output.out) == (args != ['--sets'])
    assert 'Scoring complete: scored = related' in output.out


def test_cli_missing_data_keeps_help_tree_and_failure_status(monkeypatch,capsys):
    def missing(path):
        raise ValueError('missing configuration')
    monkeypatch.setattr(tool, 'read_sets', missing)
    assert tool.main([], script_path='unused') == 1
    output = capsys.readouterr()
    assert 'Usage:' in output.out and 'Commit sets:' in output.out
    assert 'unavailable' in output.out and 'missing configuration' in output.err
