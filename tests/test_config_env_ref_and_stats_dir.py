"""Tests for ${env:NAME} references and the paths.stats_dir setting (v20.2.0)."""
import json
import os

import pytest

from lib.config import load_config, load_config_with_raw

KERNEL = {'source_dir': '/linux', 'rev_old': 'v6.8', 'rev_new': 'HEAD'}


def _write(tmp_path, data, name='cfg.json'):
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding='utf-8')
    return str(p)


def test_env_reference_is_taken_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('KCAP_TEST_ROOT', str(tmp_path / 'root'))
    cfg = _write(tmp_path, {'paths': {'work_dir': '${env:KCAP_TEST_ROOT}/work'}, 'kernel': KERNEL})
    assert load_config(cfg)['paths']['work_dir'] == str(tmp_path / 'root' / 'work')


@pytest.mark.parametrize('value', [None, ''])
def test_unset_or_empty_env_reference_is_a_clear_error(tmp_path, monkeypatch, value):
    if value is None:
        monkeypatch.delenv('KCAP_TEST_ROOT', raising=False)
    else:
        monkeypatch.setenv('KCAP_TEST_ROOT', value)
    cfg = _write(tmp_path, {'paths': {'work_dir': '${env:KCAP_TEST_ROOT}/work'}, 'kernel': KERNEL})
    with pytest.raises(SystemExit) as exc:
        load_config(cfg)
    assert 'KCAP_TEST_ROOT' in str(exc.value) and 'not set' in str(exc.value)


def test_env_reference_ignores_config_variables_of_the_same_name(tmp_path, monkeypatch):
    monkeypatch.setenv('KCAP_TEST_ROOT', '/from-env')
    cfg = _write(tmp_path, {'vars': {'KCAP_TEST_ROOT': '/from-vars'},
                            'paths': {'work_dir': '${env:KCAP_TEST_ROOT}/w',
                                      'cache_dir': '${KCAP_TEST_ROOT}/c'},
                            'kernel': KERNEL})
    loaded = load_config(cfg)
    assert loaded['paths']['work_dir'] == '/from-env/w'
    assert loaded['paths']['cache_dir'] == '/from-vars/c'


def test_workspace_declared_through_env_reference(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE', str(tmp_path))
    cfg = _write(tmp_path, {'vars': {'WORKSPACE': '${env:WORKSPACE}'},
                            'paths': {'work_dir': '${WORKSPACE}/work'}, 'kernel': KERNEL})
    loaded = load_config(cfg)
    assert loaded['vars']['WORKSPACE'] == str(tmp_path)
    assert loaded['paths']['work_dir'] == str(tmp_path / 'work')


def test_workspace_env_reference_without_environment_fails(tmp_path, monkeypatch):
    monkeypatch.delenv('WORKSPACE', raising=False)
    cfg = _write(tmp_path, {'vars': {'WORKSPACE': '${env:WORKSPACE}'},
                            'paths': {'work_dir': '${WORKSPACE}/work'}, 'kernel': KERNEL})
    with pytest.raises(SystemExit, match='WORKSPACE'):
        load_config(cfg)


def test_env_reference_is_expanded_in_the_manifest_copy(tmp_path, monkeypatch):
    monkeypatch.setenv('KCAP_TEST_ROOT', '/from-env')
    cfg = _write(tmp_path, {'vars': {'ROOT': '${env:KCAP_TEST_ROOT}'},
                            'paths': {'work_dir': '${ROOT}/w'}, 'kernel': KERNEL})
    _, manifest = load_config_with_raw(cfg)
    assert '${env:' not in json.dumps(manifest)


def test_stats_dir_defaults_to_workspace_pipeline_stats(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE', str(tmp_path))
    cfg = _write(tmp_path, {'paths': {'work_dir': '${WORKSPACE}/work'}, 'kernel': KERNEL})
    assert load_config(cfg)['paths']['stats_dir'] == str(tmp_path / 'pipeline_stats')


def test_stats_dir_explicit_value_wins_and_relative_is_resolved(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE', str(tmp_path))
    cfg = _write(tmp_path, {'paths': {'stats_dir': 'my_stats'}, 'kernel': KERNEL})
    assert load_config(cfg)['paths']['stats_dir'] == str(tmp_path / 'my_stats')
    cfg = _write(tmp_path, {'paths': {'stats_dir': '/abs/stats'}, 'kernel': KERNEL}, 'abs.json')
    assert load_config(cfg)['paths']['stats_dir'] == '/abs/stats'


def test_stats_dir_absent_without_workspace_and_setting(tmp_path, monkeypatch):
    monkeypatch.delenv('WORKSPACE', raising=False)
    cfg = _write(tmp_path, {'paths': {'work_dir': str(tmp_path / 'w')}, 'kernel': KERNEL})
    assert 'stats_dir' not in load_config(cfg)['paths']


def test_shipped_vars_paths_fragment_declares_env_workspace_and_stats_dir():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, 'configs', 'conf.d', '00_vars_paths.json'), encoding='utf-8') as stream:
        text = stream.read()
    assert '"WORKSPACE": "${env:WORKSPACE}"' in text
    assert '"stats_dir": "${WORKSPACE}/pipeline_stats"' in text
