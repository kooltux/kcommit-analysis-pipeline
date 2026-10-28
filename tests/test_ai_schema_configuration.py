"""Configuration fragments, relocation and AI validation policy stay consistent."""
import json
from pathlib import Path
import shutil

import pytest
from lib.config import CONFIG_SCHEMA, ai_active, load_config, load_json
from lib.resources import resource_path
from lib.validation import _schema_problems, validate_config_only
from lib import ai_schema_validation as checks

ROOT = Path(__file__).resolve().parents[1]


def test_all_fragments_use_registered_keys():
    fragments = sorted((ROOT / 'configs' / 'conf.d').glob('*.json'))
    assert len(fragments) == 8
    for path in fragments:
        value = load_json(path)
        assert isinstance(value, dict)
        for section, values in value.items():
            if section == 'vars':
                continue
            assert section in CONFIG_SCHEMA, (path, section)
            assert set(values) <= set(CONFIG_SCHEMA[section]), (path, section)


def test_relocated_full_example_and_initial_anchor(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE', str(tmp_path / 'workspace'))
    monkeypatch.setenv('TOOLDIR', str(ROOT))
    shutil.copytree(ROOT / 'configs' / 'conf.d', tmp_path / 'conf.d')
    main = tmp_path / 'example.json'
    shutil.copyfile(ROOT / 'configs' / 'example-arm-embedded-full.json', main)
    cfg = load_config(str(main))
    assert _schema_problems(cfg) == []
    assert ai_active(cfg)
    assert len([p for p in cfg['_meta']['loaded_files'] if 'conf.d' in str(p)]) == 8
    assert Path(resource_path(cfg, cfg['ai']['schemas_dir'])) == (
        ROOT / 'configs' / 'ai' / 'schemas')
    assert checks.SCHEMA_DIR == ROOT / 'configs' / 'ai' / 'schemas'
    cfg['ai']['schemas_dir'] = 'custom/schemas'
    cfg['_meta']['vars']['CONFIGDIR'] = str(tmp_path / 'not-the-anchor')
    assert resource_path(cfg, cfg['ai']['schemas_dir']) == str(tmp_path / 'custom/schemas')


@pytest.mark.parametrize('ai', [None, {'enabled': False}, {'enabled': True}])
def test_bundled_checks_are_unconditional_product_checks_are_gated(tmp_path, monkeypatch, ai):
    monkeypatch.setattr(checks, 'SCHEMA_DIR', tmp_path / 'missing-bundled')
    cfg = {'kernel': {'rev_old': 'a', 'rev_new': 'b'},
           'paths': {'work_dir': str(tmp_path / 'work')},
           '_meta': {'initial_config_dir': str(tmp_path)}}
    if ai is not None:
        cfg['ai'] = dict(ai, schemas_dir='missing-product')
    problems, _ = validate_config_only(cfg)
    assert any('missing-bundled' in p and 'input.json' in p for p in problems)
    assert any('ai.schemas_dir' in p for p in problems) == ai_active(cfg)


def test_product_resource_selection_does_not_fall_back(tmp_path):
    config = tmp_path / 'product.json'
    config.write_text(json.dumps({'kernel': {'rev_old': 'a', 'rev_new': 'b'},
                                 'ai': {'schemas_dir': 'owned'}}), encoding='utf-8')
    cfg = load_config(str(config))
    assert resource_path(cfg, cfg['ai']['schemas_dir']) == str(tmp_path / 'owned')
