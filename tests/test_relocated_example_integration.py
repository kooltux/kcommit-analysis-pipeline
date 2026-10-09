"""Relocated shipped-example integration for the v20.0.0 loader/resource contract."""
import json
import shutil
from pathlib import Path

from lib.config import load_config_with_raw
from lib.manifest import CACHE_FILES
from lib.profile_rules import compile_rules_for_config
from lib.stages.st08_prepare_ai import run as prepare_ai


CONFIGS = Path(__file__).resolve().parents[1] / 'configs'


def test_relocated_nested_example_keeps_explicit_resources_and_provenance(tmp_path, monkeypatch):
    product = tmp_path / 'product'
    product.mkdir()
    shutil.copy2(CONFIGS / 'example-arm-embedded-full.json', product)
    shutil.copytree(CONFIGS / 'conf.d', product / 'conf.d')
    nested = product / 'nested'
    nested.mkdir()
    entry = nested / 'entry.json'
    entry.write_text(json.dumps({'include': ['example-arm-embedded-full.json']}))
    root = product / 'root.json'
    root.write_text(json.dumps({'include': ['nested/entry.json']}))
    workspace = tmp_path / 'workspace'
    monkeypatch.setenv('WORKSPACE', str(workspace))
    monkeypatch.setenv('TOOLDIR', str(CONFIGS.parent))
    other = tmp_path / 'other_cwd'
    other.mkdir()
    monkeypatch.chdir(other)

    runtime, manifest = load_config_with_raw(root)
    assert runtime['_meta']['initial_config_dir'] == str(product)
    assert runtime['_meta']['loaded_files'][:3] == [
        str(root), str(entry), str(product / 'example-arm-embedded-full.json')]
    assert len(runtime['_meta']['loaded_files']) == 3 + len(list((CONFIGS / 'conf.d').glob('*.json')))
    assert len(runtime['_meta']['include_events']) >= len(runtime['_meta']['loaded_files']) - 1
    assert runtime['paths']['assets_dir'] == manifest['paths']['assets_dir'] == str(CONFIGS / 'assets')
    assert runtime['paths']['templates_dir'] == manifest['reports']['templates_dir'] == str(CONFIGS / 'html')
    assert runtime['paths']['scoring_dir'] == manifest['scoring']['scoring_dir'] == str(CONFIGS / 'scoring')
    assert runtime['paths']['profiles_dirs'] == manifest['profiles']['profiles_dirs'] == [str(CONFIGS / 'profiles')]
    assert runtime['paths']['rules_dirs'] == manifest['rules']['rules_dirs'] == [str(CONFIGS / 'rules')]
    for key, filename in [('prompt_path', 'ai_analysis_prompt.md'),
                          ('front_page_path', 'ai_server_front_page.md'),
                          ('result_schema_path', 'ai_analysis_result_schema.json')]:
        assert runtime['ai'][key] == manifest['ai'][key] == str(CONFIGS / 'ai' / filename)
    assert '_meta' not in manifest

    cache = Path(runtime['paths']['cache_dir'])
    compiled = compile_rules_for_config(runtime, cache_dir=str(cache))
    assert set(compiled) == set(runtime['profiles']['active'])
    assert (cache / 'compiled_rules.json').is_file()
    (cache / CACHE_FILES['prefilter_kept']).write_text('[]')
    (cache / CACHE_FILES['product_map']).write_text('{}')
    summary = prepare_ai(runtime, str(cache))
    assert summary['total_commits'] == 0
    assert summary['chunk_count'] == 1
    output = Path(runtime['paths']['output_dir'])
    for filename in ['ai_analysis_prompt.md', 'ai_server_front_page.md', 'ai_analysis_result_schema.json']:
        assert (output / filename).read_bytes() == (CONFIGS / 'ai' / filename).read_bytes()
    assert (output / 'serve_ai.pyz').is_file()
