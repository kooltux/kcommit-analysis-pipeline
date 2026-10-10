"""The exported output/pipeline_config.json holds no absolute path (v20.1.1)."""
import json
import os

from lib.config import load_config, relativize_paths
from lib.stages.st07_report import _dump_merged_config


def _tree(tmp_path):
    root = os.path.realpath(str(tmp_path))
    outdir = os.path.join(root, 'work', 'output')
    os.makedirs(outdir)
    return root, outdir


def _raw(root):
    return {
        'kernel': {'source_dir': root + '/linux', 'rev_old': 'a', 'rev_new': 'b',
                   'dts_roots': [root + '/dts', '${X}/y']},
        'paths': {'work_dir': root + '/work'},
        'reports': {'css_override': '', 'title': '/not/a/path/key'},
        'ai': {'prompt_path': '/elsewhere/prompt.md', 'chunk_size': 5},
        'vars': {'WORKSPACE': root, 'CONFIGDIR': root + '/cfg/deep', 'NAME': 'plain',
                 'OUT': '${WORKSPACE}/o', 'URL': 'https://host/path', 'N': 3},
    }


def _strings(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)
    elif isinstance(node, str):
        yield node


def test_relativize_paths_converts_path_keys_lists_and_vars(tmp_path):
    root, outdir = _tree(tmp_path)
    raw = _raw(root)
    out = relativize_paths(raw, outdir)
    assert out['kernel']['source_dir'] == '../../linux'
    assert out['kernel']['dts_roots'] == ['../../dts', '${X}/y']
    assert out['paths']['work_dir'] == '..'
    assert out['ai']['prompt_path'] == os.path.relpath('/elsewhere/prompt.md', outdir)
    assert out['vars'] == {'WORKSPACE': '../..', 'CONFIGDIR': '../../cfg/deep', 'NAME': 'plain',
                           'OUT': '${WORKSPACE}/o', 'URL': 'https://host/path', 'N': 3}
    assert out['kernel']['rev_old'] == 'a' and out['ai']['chunk_size'] == 5
    assert out['reports'] == {'css_override': '', 'title': '/not/a/path/key'}
    assert raw['kernel']['source_dir'] == root + '/linux'


def test_relative_path_is_minimal_through_symlinked_prefix(tmp_path):
    """A path spelled through a symlink must not climb to / and come back down."""
    root = os.path.realpath(str(tmp_path))
    real = os.path.join(root, 'real')
    os.makedirs(os.path.join(real, 'work', 'output'))
    os.makedirs(os.path.join(real, 'linux'))
    link = os.path.join(root, 'link')
    os.symlink(real, link)
    outdir = os.path.join(real, 'work', 'output')
    cfg = {'kernel': {'source_dir': link + '/linux', 'kernel_config': link + '/linux/.config'},
           'paths': {'output_dir': link + '/work/output', 'work_dir': link + '/work'}}
    out = relativize_paths(cfg, outdir)
    assert out['kernel']['source_dir'] == '../../linux'
    assert out['kernel']['kernel_config'] == '../../linux/.config'
    assert out['paths'] == {'output_dir': '.', 'work_dir': '..'}


def test_exported_configdir_is_dot(tmp_path):
    """The exported file is the configuration: its directory is CONFIGDIR."""
    root, outdir = _tree(tmp_path)
    cfg = {'_meta': {'config_path': root + '/orig/main.json'},
           'vars': {'CONFIGDIR': root + '/orig', 'NAME': 'plain'}}
    path = _dump_merged_config(cfg, cfg, outdir)
    with open(path, encoding='utf-8') as stream:
        dumped = json.load(stream)
    assert dumped['vars'] == {'CONFIGDIR': '.', 'NAME': 'plain'}
    assert '_meta' not in dumped
    assert relativize_paths({'vars': {'CONFIGDIR': root + '/orig'}}, outdir)['vars']['CONFIGDIR'] == '../../orig'


def _write_product(root):
    """A product config relying on conventional directories next to the config file."""
    cfgdir = os.path.join(root, 'proj', 'config')
    for name in ('profiles', 'rules', 'scoring', 'html', 'assets', 'ai'):
        os.makedirs(os.path.join(cfgdir, name))
    for name in ('ai_analysis_prompt.md', 'ai_server_front_page.md',
                 'ai_analysis_result_schema.json'):
        with open(os.path.join(cfgdir, 'ai', name), 'w', encoding='utf-8') as stream:
            stream.write('{}')
    os.makedirs(os.path.join(root, 'proj', 'linux'))
    main = os.path.join(cfgdir, 'main.json')
    with open(main, 'w', encoding='utf-8') as stream:
        json.dump({'kernel': {'source_dir': '../linux', 'rev_old': 'a', 'rev_new': 'b'},
                   'profiles': {'active': {'p': 100}}, 'ai': {},
                   'vars': {'CONFIGDIR': '${CONFIGDIR}'}}, stream)
    return main


def test_exported_config_reproduces_the_run_from_the_output_directory(tmp_path, monkeypatch):
    """Conventional locations become explicit; reloading the export gives the same paths."""
    from lib.config import load_config_with_raw
    monkeypatch.setenv('WORKSPACE', str(tmp_path))
    root = os.path.realpath(str(tmp_path))
    main = _write_product(root)
    cfg, raw = load_config_with_raw(main)
    outdir = os.path.join(root, 'proj', 'run', 'output')
    os.makedirs(outdir)
    path = _dump_merged_config(cfg, raw, outdir)
    with open(path, encoding='utf-8') as stream:
        dumped = json.load(stream)
    assert not [s for s in _strings(dumped) if os.path.isabs(s)]
    assert dumped['profiles']['profiles_dirs'] == ['../../config/profiles']
    assert dumped['rules']['rules_dirs'] == ['../../config/rules']
    assert dumped['ai']['prompt_path'] == '../../config/ai/ai_analysis_prompt.md'
    assert dumped['vars']['CONFIGDIR'] == '.'
    again = load_config(path)
    for key in ('profiles_dirs', 'rules_dirs', 'scoring_dir', 'templates_dir', 'assets_dir',
                'work_dir', 'cache_dir', 'output_dir'):
        assert again['paths'][key] == cfg['paths'][key], key
    assert again['kernel']['source_dir'] == cfg['kernel']['source_dir']
    for key in ('prompt_path', 'front_page_path', 'result_schema_path'):
        assert again['ai'][key] == os.path.join(root, 'proj', 'config', 'ai',
                                                {'prompt_path': 'ai_analysis_prompt.md',
                                                 'front_page_path': 'ai_server_front_page.md',
                                                 'result_schema_path': 'ai_analysis_result_schema.json'}[key])


def test_relative_path_to_a_sibling_tree_is_minimal(tmp_path):
    root = os.path.realpath(str(tmp_path))
    outdir = os.path.join(root, 'ws', 'work', 'output')
    os.makedirs(outdir)
    cfg = {'kernel': {'source_dir': root + '/ws/kernel'},
           'paths': {'cache_dir': root + '/ws/work/cache'}}
    out = relativize_paths(cfg, outdir)
    assert out['kernel']['source_dir'] == '../../kernel'
    assert out['paths']['cache_dir'] == '../cache'


def test_nearby_directory_symlink_gives_a_shorter_path(tmp_path):
    """A far physical target reachable through a nearby symlink is spelled through it."""
    root = os.path.realpath(str(tmp_path))
    far = os.path.join(root, 'far', 'deep', 'er', 'real_tool')
    os.makedirs(os.path.join(far, 'configs', 'rules'))
    tools = os.path.join(root, 'project', 'tools')
    os.makedirs(tools)
    os.symlink(far, os.path.join(tools, 'kcap'))
    outdir = os.path.join(root, 'project', 'config', 'run', 'output')
    os.makedirs(outdir)
    cfg = {'rules': {'rules_dirs': [far + '/configs/rules']},
           'vars': {'TOOLDIR': far}}
    out = relativize_paths(cfg, outdir)
    assert out['rules']['rules_dirs'] == ['../../../tools/kcap/configs/rules']
    assert out['vars']['TOOLDIR'] == '../../../tools/kcap'


def test_symlink_alias_search_is_skipped_for_short_paths(tmp_path, monkeypatch):
    from lib import config
    root = os.path.realpath(str(tmp_path))
    outdir = os.path.join(root, 'ws', 'work', 'output')
    os.makedirs(outdir)
    calls = []
    monkeypatch.setattr(config, '_symlink_aliases', lambda base: calls.append(base) or {})
    out = relativize_paths({'kernel': {'source_dir': root + '/ws/kernel'}}, outdir)
    assert out['kernel']['source_dir'] == '../../kernel'
    assert calls == []


def test_symlink_alias_never_replaces_a_shorter_physical_path(tmp_path):
    root = os.path.realpath(str(tmp_path))
    real = os.path.join(root, 'ws', 'tool')
    os.makedirs(real)
    outdir = os.path.join(root, 'ws', 'a', 'b', 'c', 'output')
    os.makedirs(outdir)
    os.makedirs(os.path.join(root, 'zzz'))
    os.symlink(real, os.path.join(root, 'zzz', 'link'))
    out = relativize_paths({'kernel': {'source_dir': real}}, outdir)
    assert out['kernel']['source_dir'] == '../../../../tool'


def test_relative_and_unresolved_values_are_unchanged(tmp_path):
    _, outdir = _tree(tmp_path)
    cfg = {'kernel': {'source_dir': 'already/relative', 'build_dir': '~/build',
                      'kernel_config': '${CONFIGDIR}/.config'}}
    assert relativize_paths(cfg, outdir) == cfg


def test_dumped_manifest_has_no_absolute_path(tmp_path):
    root, outdir = _tree(tmp_path)
    raw = _raw(root)
    raw['reports'] = {'title': 'T'}
    path = _dump_merged_config(raw, raw, outdir)
    assert path == os.path.join(outdir, 'pipeline_config.json')
    with open(path, encoding='utf-8') as stream:
        dumped = json.load(stream)
    assert dumped['kernel']['source_dir'] == '../../linux'
    assert dumped['vars']['WORKSPACE'] == '../..'
    assert not [s for s in _strings(dumped) if os.path.isabs(s)]


def test_dumped_manifest_resolves_back_from_its_own_directory(tmp_path):
    root, outdir = _tree(tmp_path)
    raw = {'kernel': {'source_dir': root + '/linux', 'rev_old': 'a', 'rev_new': 'b'},
           'paths': {'work_dir': root + '/work'}}
    path = _dump_merged_config(raw, raw, outdir)
    cfg = load_config(path)
    assert cfg['kernel']['source_dir'] == root + '/linux'
    assert cfg['paths']['work_dir'] == root + '/work'
