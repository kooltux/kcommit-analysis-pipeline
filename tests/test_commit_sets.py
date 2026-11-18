"""Standalone commit-set algebra, exported-config paths and Stage 07 delivery."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from lib.manifest import CACHE_FILES
from lib.stages.st07_report import _copy_helper_scripts

SOURCE = Path(__file__).resolve().parents[1] / 'lib/commit_sets.py'
spec = importlib.util.spec_from_file_location('commit_set_tool', SOURCE)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)
SHAS = [format(i, '040x') for i in (5, 2, 4, 1, 3)]


@pytest.fixture
def run_data(tmp_path):
    output = tmp_path / 'output with spaces'
    cache = tmp_path / 'cache with spaces'
    output.mkdir()
    cache.mkdir()
    (output / 'scripts').mkdir()
    script = output / 'scripts/list_commits.py'
    shutil.copyfile(SOURCE, script)
    cfg = {'vars': {'DATA': '../cache with spaces', 'NESTED': '${DATA}'},
           'kernel': {'rev_old': 'vOld', 'rev_new': 'vNew'},
           'paths': {'cache_dir': '${CONFIGDIR}/${NESTED}', 'output_dir': '.'}}
    (output / 'pipeline_config.json').write_text(json.dumps(cfg))
    values = {'all': SHAS, 'related': SHAS[1:], 'scored': SHAS[1:4],
              'relevant': SHAS[1:3], 'below_threshold': SHAS[3:4],
              'displayed': SHAS[1:2]}
    for name, members in values.items():
        target = output / 'relevant_commits.json' if name == 'displayed' else cache / tool.FILES[name]
        target.write_text(json.dumps([{'commit': sha} for sha in members]))
    return output, cache, script, values


def run(run_data, *args, cwd=None, env=None):
    output, cache, script, values = run_data
    return subprocess.run([sys.executable, '-I', '-S', str(script), *args],
                          cwd=cwd or output, capture_output=True, text=True,
                          timeout=5, env=env)


def test_cache_names_follow_pipeline_manifest():
    assert tool.FILES == {name: CACHE_FILES[key] for name, key in [
        ('all', 'commits'), ('related', 'prefilter_kept'), ('scored', 'scored'),
        ('relevant', 'relevant'), ('below_threshold', 'postfilter_dropped')]}


@pytest.mark.parametrize('args', [(), ('--help',), ('-h',), ('--sets',)])
def test_help_and_counts(run_data, args):
    result = run(run_data, *args)
    assert result.returncode == 0 and result.stderr == ''
    assert ('Usage:' in result.stdout) == (args != ('--sets',))
    for name, count in [('all', 5), ('related', 4), ('scored', 3), ('relevant', 2),
                        ('prefilter_rejected', 1), ('below_threshold', 1),
                        ('displayed', 1)]:
        assert any(line.split()[-2:] == [name, str(count)] for line in result.stdout.splitlines())


@pytest.mark.parametrize('expr,indices', [
    ('all', [0, 1, 2, 3, 4]), ('filtered', [3, 4]),
    ('related & relevant', [1, 2]), ('related - relevant', [3, 4]),
    ('prefilter_rejected | below_threshold', [0, 3]),
    ('~related', [0]), ('related ^ scored', [4]),
    ('related - scored', [4]), ('relevant - displayed', [2]),
    ('(prefilter_rejected | below_threshold) & ~displayed', [0, 3]),
    ('all - all', []), ('~~all', [0, 1, 2, 3, 4]),
    ('all - related & relevant', []), ('all - (related & relevant)', [0, 3, 4]),
    ('all | related ^ relevant & displayed', [0, 1, 2, 3, 4]),
])
def test_expressions_are_unique_ordered_and_machine_readable(run_data, expr, indices):
    result = run(run_data, '--expr', expr)
    assert result.returncode == 0 and result.stderr == ''
    assert result.stdout.splitlines() == [SHAS[i] for i in indices]


@pytest.mark.parametrize('expr', ['', 'unknown', 'all all', 'all &', '(all',
                                 'all)', 'all + related', '__import__("os")',
                                 'all;print(1)', '()'])
def test_bad_expressions_fail_without_partial_stdout(run_data, expr):
    result = run(run_data, '--expr', expr)
    assert result.returncode == 2 and result.stdout == '' and 'Error:' in result.stderr


@pytest.mark.parametrize('args', [('--expr',), ('--sets', 'all'), ('--unknown',)])
def test_bad_arguments(run_data, args):
    result = run(run_data, *args)
    assert result.returncode == 2 and result.stdout == '' and 'Usage:' in result.stderr


def test_missing_is_unavailable_not_empty(run_data):
    output, cache, script, values = run_data
    (cache / tool.FILES['relevant']).unlink()
    result = run(run_data, '--sets')
    assert result.returncode == 1
    assert any(line.split()[-2:] == ['relevant', 'unavailable']
               for line in result.stdout.splitlines())
    result = run(run_data, 'filtered')
    assert result.returncode == 1 and result.stdout == ''
    assert run(run_data, 'all').returncode == 0


@pytest.mark.parametrize('body', ['{}', '[{"commit":"bad"}]', '[{"commit":null}]',
                                 '[{"commit":"' + 'a' * 40 + '","commit":"' + 'b' * 40 + '"}]', 'NaN'])
def test_malformed_data_is_not_silently_accepted(run_data, body):
    output, cache, script, values = run_data
    (cache / tool.FILES['all']).write_text(body)
    result = run(run_data, 'related')
    assert result.returncode == 1 and result.stdout == ''


def test_empty_sets_are_valid(run_data):
    output, cache, script, values = run_data
    for p in list(cache.glob('*.json')) + [output / 'relevant_commits.json']:
        p.write_text('[]')
    assert run(run_data, '--sets').returncode == 0
    result = run(run_data, '--expr', '~related')
    assert result.returncode == 0 and result.stdout == ''


def test_duplicate_ids_are_deduplicated_in_collection_order(run_data):
    output, cache, script, values = run_data
    target = cache / tool.FILES['all']
    records = json.loads(target.read_text())
    target.write_text(json.dumps(records + records[::-1]))
    assert run(run_data, 'all').stdout.splitlines() == SHAS


def test_invalid_membership_or_partition_is_reported(run_data):
    output, cache, script, values = run_data
    (cache / tool.FILES['below_threshold']).write_text(json.dumps([{'commit': SHAS[1]}]))
    assert run(run_data, 'relevant').returncode == 1
    assert run(run_data, 'filtered').returncode == 1
    (cache / tool.FILES['related']).write_text(json.dumps([{'commit': 'f' * 40}]))
    assert run(run_data, 'related').returncode == 1


def test_counts_and_help_survive_missing_or_invalid_config(run_data):
    output, cache, script, values = run_data
    config = output / 'pipeline_config.json'
    config.unlink()
    result = run(run_data)
    assert result.returncode == 1 and 'Usage:' in result.stdout and 'unavailable' in result.stdout
    config.write_text('{')
    assert run(run_data, '--help').returncode == 1
    moved = output / 'list_commits.py'
    shutil.copyfile(script, moved)
    result = subprocess.run([sys.executable, str(moved), 'all'], capture_output=True, text=True)
    assert result.returncode == 1 and 'Traceback' not in result.stderr


@pytest.mark.parametrize('path', ['${LOOP}', '${MISSING}', '${bad.name}'])
def test_variable_errors_are_explicit(run_data, path):
    output, cache, script, values = run_data
    target = output / 'pipeline_config.json'
    cfg = json.loads(target.read_text())
    cfg['vars']['LOOP'] = '${LOOP}'
    cfg['paths']['cache_dir'] = path
    target.write_text(json.dumps(cfg))
    result = run(run_data, 'all')
    assert result.returncode == 1 and result.stdout == '' and 'Traceback' not in result.stderr


def test_environment_absolute_paths_and_different_cwd(run_data, tmp_path, monkeypatch):
    output, cache, script, values = run_data
    target = output / 'pipeline_config.json'
    cfg = json.loads(target.read_text())
    cfg['paths']['cache_dir'] = '${env:COMMIT_TEST_CACHE}'
    cfg['paths']['output_dir'] = str(output)
    target.write_text(json.dumps(cfg))
    env = dict(os.environ, COMMIT_TEST_CACHE=str(cache))
    assert run(run_data, 'all', cwd=tmp_path, env=env).stdout.splitlines() == SHAS
    env.pop('COMMIT_TEST_CACHE')
    assert run(run_data, 'all', env=env).returncode == 1


def test_nesting_limit_is_explicit(run_data):
    result = run(run_data, '--expr', '(' * 80 + 'all' + ')' * 80)
    assert result.returncode == 2 and 'nesting' in result.stderr and 'Traceback' not in result.stderr


def test_stage07_always_delivers_standalone_executable_helper(tmp_path):
    output = tmp_path / 'output'
    output.mkdir()
    cfg = {'paths': {}, '_meta': {'initial_config_dir': str(tmp_path)}}
    assert _copy_helper_scripts(cfg, str(output)) == ['scripts/list_commits.py']
    target = output / 'scripts/list_commits.py'
    assert target.read_bytes() == SOURCE.read_bytes()
    assert target.stat().st_mode & 0o111 == 0o111


def test_real_exported_config_preserves_variable_and_relative_path_semantics(run_data, tmp_path):
    from lib.stages.st07_report import _dump_merged_config
    output, cache, script, values = run_data
    cfg = {'paths': {'cache_dir': str(cache), 'output_dir': str(output)},
           'kernel': {'rev_old': 'old', 'rev_new': 'new'}}
    raw = {'vars': {'WORKSPACE': str(tmp_path)}, 'kernel': cfg['kernel'],
           'paths': {'cache_dir': '${WORKSPACE}/cache with spaces',
                     'output_dir': '${WORKSPACE}/output with spaces'}}
    assert _dump_merged_config(cfg, raw, str(output))
    result = run(run_data, '--expr', 'related - relevant')
    assert result.returncode == 0 and result.stderr == ''
    assert result.stdout.splitlines() == SHAS[3:]


def test_script_uses_only_standard_library_and_never_eval():
    import ast
    tree = ast.parse(SOURCE.read_text())
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert imports <= {'json', 'os', 'sys', 're'}
    assert not any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in ('eval', 'exec', 'compile') for node in ast.walk(tree))
