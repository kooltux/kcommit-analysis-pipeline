"""Schema-driven path/content validation and AI gating (v20.1.0)."""
import json
from argparse import Namespace
from pathlib import Path

import pytest

from lib import content_checks
from lib.config import CONFIG_SCHEMA, ai_active, load_config
from lib.validation import validate_config_only, validate_inputs

CONFIGS = Path(__file__).resolve().parents[1] / 'configs'
KNOWN_ATTRS = {'type', 'list', 'required', 'kind', 'access', 'needs', 'severity',
               'default', 'content', 'enum', 'min', 'max'}
GOOD_SCHEMA = {'type': 'object', 'properties': {'results': {'type': 'array'}}}


def _ai_dir(tmp_path, prompt='prompt', page='# page', schema=GOOD_SCHEMA):
    ai = tmp_path / 'ai'
    ai.mkdir()
    if prompt is not None:
        (ai / 'ai_analysis_prompt.md').write_text(prompt, encoding='utf-8')
    if page is not None:
        (ai / 'ai_server_front_page.md').write_text(page, encoding='utf-8')
    if schema is not None:
        (ai / 'ai_analysis_result_schema.json').write_text(
            schema if isinstance(schema, str) else json.dumps(schema), encoding='utf-8')
    return ai


def _cfg(tmp_path, **extra):
    cfg = {
        'paths': {'work_dir': str(tmp_path / 'work')},
        'kernel': {'source_dir': str(tmp_path), 'rev_old': 'a', 'rev_new': 'b'},
        'profiles': {'active': {'security_fixes': 100}},
        '_meta': {'initial_config_dir': str(tmp_path)},
    }
    cfg.update(extra)
    return cfg


# ── schema self-test ──

def test_schema_attributes_are_known_and_consistent():
    for section, specs in CONFIG_SCHEMA.items():
        for key, spec in specs.items():
            if key == '__type__':
                continue
            assert set(spec) <= KNOWN_ATTRS, (section, key)
            if spec['type'] == 'path':
                assert spec.get('kind') in ('file', 'dir'), (section, key)
            else:
                assert not ({'kind', 'access', 'content', 'default'} & set(spec)), (section, key)
            if 'content' in spec:
                assert spec['kind'] == 'file' and spec['content'] in content_checks.CHECKERS
            assert spec.get('severity', 'error') in ('error', 'notice')
            assert spec.get('access', 'read') in ('read', 'create')
            assert spec.get('needs', 'always') in ('always', 'ai', 'html')


def test_schema_declares_ai_keys():
    assert {'enabled', 'prompt_path', 'front_page_path', 'result_schema_path',
            'chunk_size'} <= set(CONFIG_SCHEMA['ai'])


# ── content checkers ──

def test_content_checkers(tmp_path):
    empty = tmp_path / 'empty.md'
    empty.write_text('  \n')
    binary = tmp_path / 'bin'
    binary.write_bytes(b'\xff\xfe\x00')
    bad_json = tmp_path / 'bad.json'
    bad_json.write_text('{')
    wrong = tmp_path / 'wrong.json'
    wrong.write_text(json.dumps({'type': 'object', 'properties': {}}))
    good = tmp_path / 'good.json'
    good.write_text(json.dumps(GOOD_SCHEMA))
    assert content_checks.check_markdown(str(empty)) == 'is empty'
    assert content_checks.check_text(str(empty)) is None
    assert 'UTF-8' in content_checks.check_text(str(binary))
    assert 'not valid JSON' in content_checks.check_json(str(bad_json))
    assert 'not a valid AI result schema' in content_checks.check_ai_result_schema(str(wrong))
    assert content_checks.check_ai_result_schema(str(good)) is None


# ── AI gating ──

def test_ai_assets_ok_when_present(tmp_path):
    _ai_dir(tmp_path)
    problems, _ = validate_config_only(_cfg(tmp_path, ai={}))
    assert not [p for p in problems if p.startswith('ai.')]


@pytest.mark.parametrize('missing,key', [
    ({'prompt': None}, 'ai.prompt_path'),
    ({'page': None}, 'ai.front_page_path'),
    ({'schema': None}, 'ai.result_schema_path')])
def test_missing_ai_asset_is_a_problem(tmp_path, missing, key):
    _ai_dir(tmp_path, **missing)
    problems, _ = validate_config_only(_cfg(tmp_path, ai={}))
    assert any(p.startswith(key + ': file not found') for p in problems)


def test_invalid_ai_asset_content_is_a_problem(tmp_path):
    _ai_dir(tmp_path, prompt='  ', page='', schema='{')
    problems, _ = validate_config_only(_cfg(tmp_path, ai={}))
    assert any(p.startswith('ai.prompt_path: is empty') for p in problems)
    assert any(p.startswith('ai.front_page_path: is empty') for p in problems)
    assert any(p.startswith('ai.result_schema_path: is not valid JSON') for p in problems)


def test_explicit_ai_paths_are_checked(tmp_path):
    _ai_dir(tmp_path)
    ai = {'prompt_path': str(tmp_path / 'nope.md')}
    problems, _ = validate_config_only(_cfg(tmp_path, ai=ai))
    assert any(p.startswith('ai.prompt_path: file not found') and 'nope.md' in p for p in problems)


@pytest.mark.parametrize('section', [None, {'enabled': False}])
def test_inactive_ai_is_not_validated(tmp_path, section):
    cfg = _cfg(tmp_path)
    if section is not None:
        cfg['ai'] = dict(section, prompt_path=str(tmp_path / 'nope.md'))
    assert not ai_active(cfg)
    problems, _ = validate_config_only(cfg)
    assert not [p for p in problems if p.startswith('ai.') and 'unknown' not in p]


def test_chunk_size_must_be_positive_int(tmp_path):
    _ai_dir(tmp_path)
    for bad in (0, -1, True):
        problems, _ = validate_config_only(_cfg(tmp_path, ai={'chunk_size': bad}))
        assert any(p.startswith('ai.chunk_size') for p in problems), bad
    problems, _ = validate_config_only(_cfg(tmp_path, ai={'chunk_size': 5}))
    assert not any(p.startswith('ai.chunk_size') for p in problems)


def test_enabled_must_be_bool(tmp_path):
    problems, _ = validate_config_only(_cfg(tmp_path, ai={'enabled': 'yes'}))
    assert any(p.startswith('ai.enabled') for p in problems)


# ── other path keys ──

def test_templates_dir_needed_only_with_html_output(tmp_path):
    missing = str(tmp_path / 'no_html')
    cfg = _cfg(tmp_path)
    cfg['paths']['templates_dir'] = missing
    problems, _ = validate_config_only(cfg)
    assert any(p.startswith('paths.templates_dir') for p in problems)
    cfg['reports'] = {'outputs': ['csv']}
    problems, _ = validate_config_only(cfg)
    assert not any(p.startswith('paths.templates_dir') for p in problems)


def test_css_override_must_exist_when_html(tmp_path):
    cfg = _cfg(tmp_path, reports={'outputs': ['html'], 'css_override': str(tmp_path / 'x.css')})
    problems, _ = validate_config_only(cfg)
    assert any(p.startswith('reports.css_override: file not found') for p in problems)


def test_optional_kernel_inputs_are_notices(tmp_path):
    cfg = _cfg(tmp_path)
    cfg['kernel'].update(kernel_build_log=str(tmp_path / 'b.log'),
                         yocto_build_log=str(tmp_path / 'y.log'),
                         dts_roots=[str(tmp_path), str(tmp_path / 'gone')])
    problems, notices = validate_config_only(cfg)
    assert not any('build_log' in p or 'dts_roots' in p for p in problems)
    assert any('kernel.kernel_build_log' in n for n in notices)
    assert any('kernel.yocto_build_log' in n for n in notices)
    assert any(n.startswith('notice: kernel.dts_roots[1]') for n in notices)
    assert not any('kernel.dts_roots[0]' in n for n in notices)


def test_wrong_kind_is_reported(tmp_path):
    cfg = _cfg(tmp_path, reports={'outputs': ['html'], 'css_override': str(tmp_path)})
    problems, _ = validate_config_only(cfg)
    assert any(p.startswith('reports.css_override: path is not a file') for p in problems)


def test_create_access_dirs_may_be_absent_but_not_files(tmp_path):
    cfg = _cfg(tmp_path)
    cfg['paths']['cache_dir'] = str(tmp_path / 'later')
    problems, _ = validate_config_only(cfg)
    assert not any(p.startswith('paths.cache_dir') for p in problems)
    (tmp_path / 'afile').write_text('x')
    cfg['paths']['cache_dir'] = str(tmp_path / 'afile')
    problems, _ = validate_config_only(cfg)
    assert any(p.startswith('paths.cache_dir: path is not a directory') for p in problems)


def test_list_item_errors_use_dotted_index_names(tmp_path):
    cfg = _cfg(tmp_path)
    cfg['paths']['profiles_dirs'] = ['/ok', 5]
    problems, _ = validate_config_only(cfg)
    assert any(p.startswith('paths.profiles_dirs[1]: item must be path') for p in problems)


# ── shipped example and command ──

def test_shipped_example_has_no_path_problems(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACE', str(tmp_path))
    cfg = load_config(str(CONFIGS / 'example-arm-embedded-full.json'))
    assert ai_active(cfg)
    problems, _ = validate_config_only(cfg)
    assert not [p for p in problems if 'not found' in p or 'not readable' in p
                or p.startswith('ai.') or 'unknown' in p], problems


def _validate_args(path):
    return Namespace(config=str(path), override=None)


def test_validate_command_reports_missing_include_without_traceback(tmp_path, caplog):
    from lib.commands.cmd_validate import cmd_validate
    cfg = tmp_path / 'main.json'
    cfg.write_text(json.dumps({'include': ['conf.d/missing.json']}))
    with pytest.raises(SystemExit) as excinfo:
        cmd_validate(_validate_args(cfg))
    assert excinfo.value.code == 1
    assert 'missing.json' in caplog.text


def test_validate_command_fails_on_missing_ai_asset(tmp_path, caplog):
    from lib.commands.cmd_validate import cmd_validate
    (tmp_path / 'profiles').mkdir()
    (tmp_path / 'profiles' / 'security_fixes.json').write_text('{}')
    (tmp_path / 'rules').mkdir()
    (tmp_path / 'html').mkdir()
    cfg = tmp_path / 'main.json'
    cfg.write_text(json.dumps({
        'kernel': {'rev_old': 'a', 'rev_new': 'b'},
        'profiles': {'active': {'security_fixes': 100}},
        'ai': {}}))
    with pytest.raises(SystemExit) as excinfo:
        cmd_validate(_validate_args(cfg))
    assert excinfo.value.code == 1
    assert 'ai.prompt_path' in caplog.text
    cfg.write_text(json.dumps({
        'kernel': {'rev_old': 'a', 'rev_new': 'b'},
        'profiles': {'active': {'security_fixes': 100}},
        'ai': {'enabled': False}}))
    cmd_validate(_validate_args(cfg))
