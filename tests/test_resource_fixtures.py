"""Report fixtures must produce verifiable caches from local sources."""
import json

from lib.profile_rules import _current_schema_hash, load_profile_rules
from resource_fixtures import seed_resources


def test_report_fixture_has_a_valid_local_cache(tmp_path):
    cfg = {'paths': {'cache_dir': str(tmp_path / 'cache')},
           'profiles': {'active': {'security_fixes': 100}}}
    seed_resources(cfg, tmp_path)
    doc = json.loads((tmp_path / 'cache' / 'compiled_rules.json').read_text())
    assert doc['schema_hash'] == _current_schema_hash(cfg)
    assert doc['schema_hash'] not in ('test', 'test-sentinel-hash')
    assert set(load_profile_rules(cfg)) == {'security_fixes'}
    assert cfg['paths']['profiles_dirs'] == [str(tmp_path / 'fixture_profiles')]
    assert cfg['paths']['rules_dirs'] == [str(tmp_path / 'fixture_rules')]


def test_report_fixture_preserves_explicit_template_override(tmp_path):
    templates = str(tmp_path / 'custom_html')
    cfg = {'paths': {'cache_dir': str(tmp_path / 'cache'), 'templates_dir': templates},
           'profiles': {'active': {'local': 10}}}
    seed_resources(cfg, tmp_path)
    assert cfg['paths']['templates_dir'] == templates
