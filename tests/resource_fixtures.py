"""Explicit resources and valid rule caches for report/command integration tests."""
import json
import os

from lib.profile_rules import compile_rules_for_config


def seed_resources(cfg, root):
    profiles = os.path.join(str(root), 'fixture_profiles')
    rules = os.path.join(str(root), 'fixture_rules')
    rule = os.path.join(rules, 'fixture_rule')
    os.makedirs(profiles, exist_ok=True)
    os.makedirs(rule, exist_ok=True)
    with open(os.path.join(rule, 'keywords_whitelist.txt'), 'w', encoding='utf-8') as stream:
        stream.write('fixture-keyword\n')
    active = (cfg.get('profiles') or {}).get('active') or []
    for name in active:
        with open(os.path.join(profiles, name + '.json'), 'w', encoding='utf-8') as stream:
            json.dump({'description': 'Fixture profile', 'rules': {'fixture_rule': 10}}, stream)
    paths = cfg.setdefault('paths', {})
    paths['profiles_dirs'] = [profiles]
    paths['rules_dirs'] = [rules]
    cfg.setdefault('profiles', {})['profiles_dirs'] = [profiles]
    cfg.setdefault('rules', {})['rules_dirs'] = [rules]
    cfg.setdefault('_meta', {})['initial_config_dir'] = os.path.abspath(str(root))
    samples = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'configs')
    if not paths.get('templates_dir'):
        paths['templates_dir'] = os.path.join(samples, 'html')
    if not paths.get('assets_dir'):
        paths['assets_dir'] = os.path.join(samples, 'assets')
    cfg.setdefault('reports', {}).setdefault('templates_dir', paths['templates_dir'])
    cfg.setdefault('ai', {}).setdefault('prompt_path', os.path.join(samples, 'ai', 'ai_analysis_prompt.md'))
    if active:
        compile_rules_for_config(cfg, cache_dir=paths['cache_dir'])
