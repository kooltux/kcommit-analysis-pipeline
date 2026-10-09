"""Initial-root resource selection and fail-closed profile/rule cache tests."""
import json
import shutil

import pytest

from lib.resources import resource_path
from lib.profile_rules import load_profile_rules


@pytest.mark.parametrize('subdir', ['assets', 'html', 'scoring', 'ai', 'profiles', 'rules'])
def test_resource_defaults_use_initial_anchor(tmp_path, monkeypatch, subdir):
    initial = tmp_path / 'product'
    other = tmp_path / 'other'
    other.mkdir()
    monkeypatch.chdir(other)
    cfg = {'_meta': {'initial_config_dir': str(initial), 'config_dir': str(other)},
           'vars': {'CONFIGDIR': str(other), 'TOOLDIR': str(other)}}
    assert resource_path(cfg, None, subdir) == str(initial / subdir)


def test_explicit_resource_paths_are_respected(tmp_path):
    cfg = {'_meta': {'initial_config_dir': str(tmp_path)}}
    assert resource_path(cfg, 'custom/assets', 'assets') == str(tmp_path / 'custom' / 'assets')
    absolute = str(tmp_path.parent / 'shared')
    assert resource_path(cfg, absolute, 'assets') == absolute


def source_config(tmp_path, name='sec'):
    profiles = tmp_path / 'profiles'
    rules = tmp_path / 'rules'
    profiles.mkdir(parents=True)
    (rules / 'r1').mkdir(parents=True)
    (profiles / (name + '.json')).write_text('{"rules": {"r1": 10}}', encoding='utf-8')
    (rules / 'r1' / 'keywords_whitelist.txt').write_text('local-keyword', encoding='utf-8')
    return {'paths': {'profiles_dirs': [str(profiles)], 'rules_dirs': [str(rules)],
                      'cache_dir': str(tmp_path / 'cache')}, 'profiles': {'active': [name]}}


@pytest.mark.parametrize('removed', ['profile', 'rule'])
def test_cached_rules_cannot_hide_missing_sources(tmp_path, removed):
    cfg = source_config(tmp_path)
    load_profile_rules(cfg)
    if removed == 'profile':
        (tmp_path / 'profiles' / 'sec.json').unlink()
    else:
        shutil.rmtree(tmp_path / 'rules' / 'r1')
    with pytest.raises(RuntimeError, match='not found'):
        load_profile_rules(cfg)


def test_identical_sources_in_new_roots_invalidate_cache(tmp_path):
    first = source_config(tmp_path / 'first')
    second = source_config(tmp_path / 'second')
    second['paths']['cache_dir'] = first['paths']['cache_dir']
    cache = tmp_path / 'first' / 'cache' / 'compiled_rules.json'
    load_profile_rules(first)
    before = json.loads(cache.read_text())['schema_hash']
    result = load_profile_rules(second)
    after = json.loads(cache.read_text())['schema_hash']
    assert before != after
    assert result['sec']['rules']['r1']['_sources_keywords_whitelist'][0][0].startswith(
        str(tmp_path / 'second' / 'rules'))


def test_active_profile_identity_is_part_of_cache_hash(tmp_path):
    cfg = source_config(tmp_path)
    load_profile_rules(cfg)
    shutil.copyfile(tmp_path / 'profiles' / 'sec.json', tmp_path / 'profiles' / 'other.json')
    cfg['profiles']['active'] = ['other']
    assert set(load_profile_rules(cfg)) == {'other'}


def test_unverifiable_hash_forces_recompile(tmp_path, monkeypatch):
    from lib import profile_rules
    cfg = source_config(tmp_path)
    load_profile_rules(cfg)
    monkeypatch.setattr(profile_rules, '_current_schema_hash', lambda cfg: None)
    sentinel = {'recompiled': True}
    monkeypatch.setattr(profile_rules, 'compile_rules_for_config', lambda cfg, cache: sentinel)
    assert load_profile_rules(cfg) is sentinel


def test_loader_resource_defaults_ignore_builtin_overrides(tmp_path):
    from lib.config import load_config
    root = tmp_path / 'root.json'
    root.write_text(json.dumps({'vars': {'CONFIGDIR': '/other', 'TOOLDIR': '/other'}}))
    cfg = load_config(root)
    assert cfg['paths']['assets_dir'] == str(tmp_path / 'assets')
    assert cfg['paths']['templates_dir'] == str(tmp_path / 'html')


def test_missing_html_does_not_use_samples(tmp_path):
    from lib.html_report import generate_html_report
    cfg = {'_meta': {'initial_config_dir': str(tmp_path)}}
    with pytest.raises(RuntimeError, match='HTML template missing'):
        generate_html_report([], {}, {}, str(tmp_path / 'report.html'), cfg=cfg)
    assert not (tmp_path / 'report.html').exists()


def test_missing_ai_resources_do_not_use_samples(tmp_path):
    from lib.stages.st08_prepare_ai import run
    cfg = {'paths': {'output_dir': str(tmp_path / 'output')},
           '_meta': {'initial_config_dir': str(tmp_path)}}
    with pytest.raises(ValueError, match='ai.front_page_path'):
        run(cfg, str(tmp_path / 'cache'))
    assert not (tmp_path / 'output').exists()


def test_legacy_prompt_remains_optional_without_samples(tmp_path):
    from lib.stages.st07_report import _get_ai_analysis_prompt
    cfg = {'_meta': {'initial_config_dir': str(tmp_path)}}
    assert _get_ai_analysis_prompt(cfg) == ''


def test_hints_remain_optional_without_samples(tmp_path):
    from lib.kbuild import infer_touched_paths
    cfg = {'paths': {}, '_meta': {'initial_config_dir': str(tmp_path)}}
    assert infer_touched_paths('usb: fix reset', cfg) == []


def test_product_prompt_and_hints_defaults_are_consumed(tmp_path):
    from lib.stages.st07_report import _get_ai_analysis_prompt
    from lib.kbuild import infer_touched_paths
    (tmp_path / 'ai').mkdir()
    (tmp_path / 'ai' / 'ai_analysis_prompt.md').write_text('Product-only prompt')
    (tmp_path / 'scoring').mkdir()
    (tmp_path / 'scoring' / 'subsystem_path_hints.json').write_text(
        json.dumps({'usb:': ['product-only/']}))
    cfg = {'paths': {}, '_meta': {'initial_config_dir': str(tmp_path)}}
    assert _get_ai_analysis_prompt(cfg) == 'Product-only prompt'
    assert infer_touched_paths('usb: fix reset', cfg) == ['product-only/']
