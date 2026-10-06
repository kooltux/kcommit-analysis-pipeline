"""Tests for the required built-in variable check in lib.config (v19.11.1).

An empty WORKSPACE/TOOLDIR/CONFIGDIR/CWD must make load_config() fail with a
clear error when the configuration references it, instead of silently
expanding ${WORKSPACE}/work to /work.  Configurations that never reference
the variable keep working without it.
"""
import json
from pathlib import Path

import pytest

from lib.config import load_config, load_config_with_raw

KERNEL = {'source_dir': '/linux', 'rev_old': 'v6.8', 'rev_new': 'HEAD'}


def _write(tmp_path, data, name='cfg.json'):
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding='utf-8')
    return str(p)


def test_unset_workspace_referenced_raises(tmp_path, monkeypatch):
    monkeypatch.delenv('WORKSPACE', raising=False)
    cfg = _write(tmp_path, {'paths': {'work_dir': '${WORKSPACE}/work'}, 'kernel': KERNEL})
    with pytest.raises(SystemExit) as exc:
        load_config(cfg)
    assert 'WORKSPACE' in str(exc.value)
    assert 'not set' in str(exc.value)


def test_empty_workspace_referenced_raises(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE', '')
    cfg = _write(tmp_path, {'paths': {'work_dir': '${WORKSPACE}/work'}, 'kernel': KERNEL})
    with pytest.raises(SystemExit):
        load_config(cfg)


def test_unset_workspace_not_referenced_loads(tmp_path, monkeypatch):
    monkeypatch.delenv('WORKSPACE', raising=False)
    cfg = _write(tmp_path, {'paths': {'work_dir': str(tmp_path / 'w')}, 'kernel': KERNEL})
    loaded = load_config(cfg)
    assert loaded['paths']['work_dir'] == str(tmp_path / 'w')


def test_workspace_from_environment_loads(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE', str(tmp_path))
    cfg = _write(tmp_path, {'paths': {'work_dir': '${WORKSPACE}/work'}, 'kernel': KERNEL})
    loaded = load_config(cfg)
    assert loaded['paths']['work_dir'] == str(tmp_path / 'work')


def test_workspace_defined_in_vars_loads(tmp_path, monkeypatch):
    monkeypatch.delenv('WORKSPACE', raising=False)
    cfg = _write(tmp_path, {
        'vars': {'WORKSPACE': str(tmp_path)},
        'paths': {'work_dir': '${WORKSPACE}/work'},
        'kernel': KERNEL,
    })
    loaded = load_config(cfg)
    assert loaded['paths']['work_dir'] == str(tmp_path / 'work')


def test_self_referencing_workspace_var_without_env_raises(tmp_path, monkeypatch):
    """The shipped fragments declare "WORKSPACE": "${WORKSPACE}"."""
    monkeypatch.delenv('WORKSPACE', raising=False)
    cfg = _write(tmp_path, {
        'vars': {'WORKSPACE': '${WORKSPACE}'},
        'paths': {'work_dir': str(tmp_path / 'w')},
        'kernel': KERNEL,
    })
    with pytest.raises(SystemExit):
        load_config(cfg)


def test_empty_tooldir_referenced_raises(tmp_path, monkeypatch):
    monkeypatch.setenv('TOOLDIR', '')
    cfg = _write(tmp_path, {'paths': {'work_dir': '${TOOLDIR}/work'}, 'kernel': KERNEL})
    with pytest.raises(SystemExit) as exc:
        load_config(cfg)
    assert 'TOOLDIR' in str(exc.value)


def test_empty_tooldir_not_referenced_loads(tmp_path, monkeypatch):
    monkeypatch.setenv('TOOLDIR', '')
    cfg = _write(tmp_path, {'paths': {'work_dir': str(tmp_path / 'w')}, 'kernel': KERNEL})
    assert load_config(cfg)['paths']['work_dir'] == str(tmp_path / 'w')


def test_load_config_with_raw_also_raises(tmp_path, monkeypatch):
    monkeypatch.delenv('WORKSPACE', raising=False)
    cfg = _write(tmp_path, {'paths': {'work_dir': '${WORKSPACE}/work'}, 'kernel': KERNEL})
    with pytest.raises(SystemExit):
        load_config_with_raw(cfg)


def test_inherited_workspace_satisfies_check(tmp_path, monkeypatch):
    monkeypatch.delenv('WORKSPACE', raising=False)
    cfg = _write(tmp_path, {'paths': {'work_dir': '${WORKSPACE}/work'}, 'kernel': KERNEL})
    loaded = load_config(cfg, inherited_vars={'WORKSPACE': str(tmp_path)})
    assert loaded['paths']['work_dir'] == str(tmp_path / 'work')


@pytest.mark.filterwarnings('ignore::UserWarning')
def test_shipped_example_config_requires_workspace(tmp_path, monkeypatch):
    example = Path(__file__).resolve().parents[1] / 'configs' / 'example-arm-embedded-full.json'
    monkeypatch.delenv('WORKSPACE', raising=False)
    with pytest.raises(SystemExit):
        load_config(str(example))
    monkeypatch.setenv('WORKSPACE', str(tmp_path))
    loaded = load_config(str(example))
    assert loaded['paths']['work_dir'] == str(tmp_path / 'work')
