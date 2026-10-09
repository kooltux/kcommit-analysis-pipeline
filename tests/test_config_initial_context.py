"""Initial-file anchoring and shared loader context regressions."""
import json
from pathlib import Path

import pytest

from lib import config


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def test_nested_include_and_resource_paths_use_initial_base(tmp_path, monkeypatch):
    root = write(tmp_path / 'product' / 'root.json', {'include': ['conf.d/fragment.json']})
    base = root.parent
    write(base / 'conf.d' / 'fragment.json', {'include': ['shared.json']})
    write(base / 'shared.json', {'ai': {'front_page_path': 'ai/page.md'}})
    write(base / 'conf.d' / 'shared.json', {'ai': {'front_page_path': 'wrong.md'}})
    monkeypatch.chdir(tmp_path)
    cfg = config.load_config(root)
    assert cfg['ai']['front_page_path'] == str(base / 'ai' / 'page.md')
    assert cfg['_meta']['loaded_files'] == [str(root), str(base / 'conf.d' / 'fragment.json'), str(base / 'shared.json')]


def test_include_variables_are_scoped_before_traversal(tmp_path):
    root = write(tmp_path / 'root.json', {'vars': {'FIRST': 'conf.d/a.json'}, 'include': ['${FIRST}']})
    write(tmp_path / 'conf.d' / 'a.json', {'vars': {'NEXT': 'shared.json'}, 'include': ['${NEXT}']})
    write(tmp_path / 'shared.json', {'ai': {'chunk_size': 42}})
    assert config.load_config(root)['ai']['chunk_size'] == 42


def test_later_sibling_cannot_define_earlier_include(tmp_path):
    root = write(tmp_path / 'root.json', {'include': ['${LATER}', 'definitions.json']})
    write(tmp_path / 'definitions.json', {'vars': {'LATER': 'shared.json'}})
    with pytest.raises(ValueError, match='include resolution failed.*LATER'):
        config.load_config(root)


def test_runtime_and_export_share_one_snapshot(tmp_path, monkeypatch):
    root = write(tmp_path / 'root.json', {'include': ['${FRAGMENT}'],
        'vars': {'OUT': '${WORKSPACE}/out'}, 'paths': {'work_dir': '${OUT}'}})
    write(tmp_path / 'child.json', {'ai': {'chunk_size': 7}})
    calls = []
    original = config.load_json
    def tracked(path, default=None):
        calls.append(str(path))
        return original(path, default)
    monkeypatch.setattr(config, 'load_json', tracked)
    expanded, manifest = config.load_config_with_raw(root,
        inherited_vars={'FRAGMENT': 'child.json', 'WORKSPACE': '/chosen'})
    assert calls == [str(root), str(tmp_path / 'child.json')]
    assert expanded['paths']['work_dir'] == '/chosen/out'
    assert manifest['vars']['OUT'] == '/chosen/out'
    assert manifest['vars']['FRAGMENT'] == 'child.json'
    assert manifest['paths']['work_dir'] == '${OUT}'


def test_tooldir_default_is_installation_root(tmp_path, monkeypatch):
    monkeypatch.delenv('TOOLDIR', raising=False)
    root = write(tmp_path / 'custom' / 'root.json', {})
    cfg = config.load_config(root)
    assert cfg['vars']['TOOLDIR'] == str(Path(config.__file__).resolve().parents[1])


def test_builtin_override_does_not_move_initial_anchor(tmp_path):
    root = write(tmp_path / 'root.json', {'vars': {'CONFIGDIR': '/explicit'},
        'ai': {'front_page_path': 'relative.md'}, 'paths': {'work_dir': '${CONFIGDIR}/work'}})
    expanded, manifest = config.load_config_with_raw(root)
    assert expanded['_meta']['initial_config_dir'] == str(tmp_path)
    assert expanded['ai']['front_page_path'] == str(tmp_path / 'relative.md')
    assert expanded['paths']['work_dir'] == manifest['paths']['work_dir'] == '/explicit/work'


@pytest.mark.filterwarnings('ignore::UserWarning')
def test_nested_merge_provenance_retained(tmp_path):
    root = write(tmp_path / 'root.json', {'include': ['conf.d/a.json']})
    write(tmp_path / 'first.json', {'ai': {'chunk_size': 1}})
    second = write(tmp_path / 'second.json', {'ai': {'chunk_size': 2}})
    write(tmp_path / 'conf.d' / 'a.json', {'include': ['first.json', 'second.json']})
    events = config.load_config(root)['_meta']['include_events']
    assert any(event.get('source') == str(second) and event['event'] == 'scalar_replaced' for event in events)


def test_missing_include_reports_chain(tmp_path):
    root = write(tmp_path / 'root.json', {'include': ['conf.d/a.json']})
    write(tmp_path / 'conf.d' / 'a.json', {'include': ['missing.json']})
    with pytest.raises(FileNotFoundError) as exc:
        config.load_config(root)
    assert all(name in str(exc.value) for name in ['root.json', 'a.json', 'missing.json'])


def test_initial_symlink_keeps_invocation_directory(tmp_path):
    target = write(tmp_path / 'source' / 'root.json', {'include': ['child.json']})
    link = tmp_path / 'product' / 'root.json'
    link.parent.mkdir()
    link.symlink_to(target)
    write(link.parent / 'child.json', {'ai': {'chunk_size': 11}})
    assert config.load_config(link)['ai']['chunk_size'] == 11


def test_symlink_include_cycle_rejected(tmp_path):
    root = write(tmp_path / 'root.json', {'include': ['alias.json']})
    (tmp_path / 'alias.json').symlink_to(root)
    with pytest.raises(ValueError, match='cyclic include'):
        config.load_config(root)
