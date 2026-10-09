"""Built-in pass-through declarations must retain incoming values, not create cycles."""
import json

import pytest

from lib.config import load_config, load_config_with_raw


def write(tmp_path, value):
    root = tmp_path / 'root.json'
    root.write_text(json.dumps(value), encoding='utf-8')
    return root


def test_missing_workspace_passthrough_is_required_variable_error(tmp_path, monkeypatch):
    monkeypatch.delenv('WORKSPACE', raising=False)
    root = write(tmp_path, {'vars': {'WORKSPACE': '${WORKSPACE}'}})
    with pytest.raises(SystemExit, match='required variable WORKSPACE'):
        load_config(root)


@pytest.mark.parametrize('name', ['WORKSPACE', 'TOOLDIR', 'CONFIGDIR', 'CWD'])
def test_builtin_passthrough_runtime_and_export(tmp_path, name):
    value = '/incoming/' + name.lower()
    root = write(tmp_path, {'vars': {name: '${' + name + '}'},
                            'paths': {'work_dir': '${' + name + '}/work'}})
    runtime, manifest = load_config_with_raw(root, inherited_vars={name: value})
    assert runtime['vars'][name] == manifest['vars'][name] == value
    assert runtime['paths']['work_dir'] == manifest['paths']['work_dir'] == value + '/work'


def test_builtin_extension_is_not_expanded_twice_in_export(tmp_path):
    root = write(tmp_path, {'vars': {'WORKSPACE': '${WORKSPACE}/project'},
                            'paths': {'work_dir': '${WORKSPACE}/work'}})
    runtime, manifest = load_config_with_raw(root, inherited_vars={'WORKSPACE': '/incoming'})
    assert runtime['vars']['WORKSPACE'] == manifest['vars']['WORKSPACE'] == '/incoming/project'
    assert runtime['paths']['work_dir'] == manifest['paths']['work_dir'] == '/incoming/project/work'


def test_passthrough_works_in_include_scope(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE', str(tmp_path))
    (tmp_path / 'child.json').write_text('{"ai": {"chunk_size": 23}}', encoding='utf-8')
    root = write(tmp_path, {'vars': {'WORKSPACE': '${WORKSPACE}'},
                            'include': ['${WORKSPACE}/child.json']})
    assert load_config(root)['ai']['chunk_size'] == 23


def test_real_user_variable_cycle_is_still_rejected(tmp_path):
    root = write(tmp_path, {'vars': {'A': '${B}', 'B': '${A}'}})
    with pytest.raises(ValueError, match='cyclic variable reference'):
        load_config(root)
