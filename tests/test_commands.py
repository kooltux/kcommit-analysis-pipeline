"""Tests for lib.commands — cmd_validate, cmd_status, cmd_dropped, cmd_report,
and base helpers (load_state, stage_needs_run, resolve_stage, stage_extra)."""
import json, os, sys
from unittest.mock import patch, MagicMock
import pytest

from lib.commands.base import (
    load_state, stage_needs_run, resolve_stage, stage_extra,
)
from lib.pipeline_runtime import init_pipeline_state, start_stage, finish_stage
from lib.manifest import STAGE_OUTPUTS
from lib.stages import STAGES


# ── load_state ────────────────────────────────────────────────────────────────
def test_load_state_missing_file(tmp_path):
    result = load_state(str(tmp_path / 'no_state.json'))
    assert result == {}


def test_load_state_reads_stages(tmp_path):
    sp = str(tmp_path / 'state.json')
    init_pipeline_state(sp)
    t = start_stage(sp, 'collect_commits', 1, 8)
    finish_stage(sp, 'collect_commits', t)
    result = load_state(sp)
    assert 'collect_commits' in result
    assert result['collect_commits']['status'] == 'ok'


def test_load_state_corrupt_file(tmp_path):
    sp = str(tmp_path / 'bad.json')
    open(sp, 'w').write('{not valid json}')
    result = load_state(sp)
    assert result == {}


# ── resolve_stage ─────────────────────────────────────────────────────────────
def test_resolve_stage_by_name():
    idx, key = resolve_stage('collect_commits')
    assert key == 'collect_commits'
    assert isinstance(idx, int)


def test_resolve_stage_by_index():
    idx, key = resolve_stage('0')
    assert idx == 0


def test_resolve_stage_unknown():
    with pytest.raises(SystemExit):
        resolve_stage('no_such_stage')


# ── stage_needs_run ───────────────────────────────────────────────────────────
def test_stage_needs_run_no_state():
    assert stage_needs_run('collect_commits', '/tmp', {}) is True


def test_stage_needs_run_ok_but_missing_file(tmp_path):
    state = {'collect_commits': {'status': 'ok'}}
    # STAGE_OUTPUTS['collect_commits'] references files that don't exist
    assert stage_needs_run('collect_commits', str(tmp_path), state) is True


def test_stage_needs_run_ok_all_files_exist(tmp_path):
    work = str(tmp_path)
    # Write all expected output files for 'collect_commits'
    for rel in (STAGE_OUTPUTS.get('collect_commits') or []):
        full = os.path.join(work, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, 'w').write('{}')
    state = {'collect_commits': {'status': 'ok'}}
    assert stage_needs_run('collect_commits', work, state) is False


# ── stage_extra ───────────────────────────────────────────────────────────────
def test_stage_extra_none_result():
    assert stage_extra('collect_commits', None, 1.0) == {}


def test_stage_extra_collect_commits():
    commits = [{'commit': 'a'}, {'commit': 'b'}]
    extra = stage_extra('collect_commits', commits, 1.0)
    assert extra.get('commit_count') == 2


def test_stage_extra_build_context():
    ctx = {'kernel_config': ['C=y'] * 5, 'kbuild_files': ['f1', 'f2']}
    smap = {'CONFIG_USB': ['drivers/usb/hub.c']}
    extra = stage_extra('collect_build_context', (ctx, smap), 1.0)
    assert extra['enabled_config_count'] == 5
    assert extra['kbuild_file_count'] == 2
    assert extra['static_config_map_symbols'] == 1


def test_stage_extra_prefilter():
    extra = stage_extra('prefilter_commits', ([1, 2], [3], {'bl': 1}), 0.5)
    assert extra['kept_count'] == 2
    assert extra['dropped_count'] == 1


def test_stage_extra_score_commits():
    extra = stage_extra('score_commits', [1, 2, 3, 4], 1.0)
    assert extra['scored_count'] == 4


def test_stage_extra_build_product_map():
    pm = {'config_to_paths': {'A': [], 'B': []}}
    extra = stage_extra('build_product_map', pm, 1.0)
    assert extra['config_symbol_count'] == 2


def test_stage_extra_unknown_key():
    extra = stage_extra('unknown_stage', {'anything': 1}, 1.0)
    assert extra == {}


# ── cmd_validate ──────────────────────────────────────────────────────────────
def _minimal_cfg(tmp_path):
    return {
        'paths': {
            'work_dir':   str(tmp_path / 'work'),
            'cache_dir':  str(tmp_path / 'cache'),
            'output_dir': str(tmp_path / 'output'),
        },
        'kernel': {'source_dir': None, 'rev_old': 'v1', 'rev_new': 'v2',
                   'kernel_config': None},
        'filter':   {},
        'profiles': {'active': {}},
        'collect':  {},
        'reports':  {},
    }


def test_cmd_validate_ok(tmp_path, capsys):
    from lib.commands.cmd_validate import cmd_validate
    cfg = _minimal_cfg(tmp_path)
    cfg['profiles']['active'] = {'networking': 100}
    args = MagicMock()
    args.config = 'test.yaml'
    args.override = None
    # Mock validate_inputs so we don't need a real git repo or valid rev refs
    with patch('lib.commands.cmd_validate.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_validate.validate_inputs', return_value=([], [])):
        cmd_validate(args)
    out = capsys.readouterr().out
    assert 'OK' in out


def test_cmd_validate_fails_on_problems(tmp_path, capsys):
    from lib.commands.cmd_validate import cmd_validate
    cfg = _minimal_cfg(tmp_path)
    args = MagicMock()
    args.config = 'test.yaml'
    args.override = None
    with patch('lib.commands.cmd_validate.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_validate.validate_inputs',
               return_value=(['source_dir not configured'], [])):
        with pytest.raises(SystemExit):
            cmd_validate(args)


# ── cmd_status ────────────────────────────────────────────────────────────────
def test_cmd_status_empty_state(tmp_path, capsys):
    from lib.commands.cmd_status import cmd_status
    work = str(tmp_path / 'work')
    os.makedirs(work)
    cfg = _minimal_cfg(tmp_path)
    args = MagicMock()
    with patch('lib.commands.cmd_status.load_cfg', return_value=cfg):
        cmd_status(args)
    out = capsys.readouterr().out
    assert 'pending' in out.lower() or 'Status' in out


# ── cmd_dropped ───────────────────────────────────────────────────────────────
def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f)


def test_cmd_dropped_summary(tmp_path, capsys):
    from lib.commands.cmd_dropped import cmd_dropped
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['cache_dir'])
    filt = [
        {'commit': 'abc', 'subject': 'net: fix', '_filter_reason': 'path_blacklist'},
        {'commit': 'def', 'subject': 'mm: add', '_filter_reason': 'path_blacklist'},
    ]
    _write(os.path.join(cfg['paths']['cache_dir'], 'filtered_commits.json'), filt)
    args = MagicMock()
    args.reason = 'all'
    args.json = False
    args.verbose = False
    with patch('lib.commands.cmd_dropped.load_cfg', return_value=cfg):
        cmd_dropped(args)
    out = capsys.readouterr().out
    assert '2' in out


def test_cmd_dropped_json_output(tmp_path, capsys):
    from lib.commands.cmd_dropped import cmd_dropped
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['cache_dir'])
    filt = [{'commit': 'abc', 'subject': 'fix', '_filter_reason': 'bl'}]
    _write(os.path.join(cfg['paths']['cache_dir'], 'filtered_commits.json'), filt)
    args = MagicMock()
    args.reason = 'all'
    args.json = True
    args.verbose = False
    with patch('lib.commands.cmd_dropped.load_cfg', return_value=cfg):
        cmd_dropped(args)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert len(data) == 1


def test_cmd_dropped_low_score_filter(tmp_path, capsys):
    from lib.commands.cmd_dropped import cmd_dropped
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['cache_dir'])
    filt = [
        {'commit': 'a', '_filter_reason': 'score_below_threshold'},
        {'commit': 'b', '_filter_reason': 'path_blacklist'},
    ]
    _write(os.path.join(cfg['paths']['cache_dir'], 'filtered_commits.json'), filt)
    args = MagicMock()
    args.reason = 'low-score'
    args.json = True
    args.verbose = False
    with patch('lib.commands.cmd_dropped.load_cfg', return_value=cfg):
        cmd_dropped(args)
    out = capsys.readouterr().out
    data = json.loads(out)
    assert all('score_below' in c['_filter_reason'] for c in data)


def test_cmd_dropped_verbose(tmp_path, capsys):
    from lib.commands.cmd_dropped import cmd_dropped
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['cache_dir'])
    filt = [{'commit': 'abc123456789', 'subject': 'fix: something', '_filter_reason': 'bl'}]
    _write(os.path.join(cfg['paths']['cache_dir'], 'filtered_commits.json'), filt)
    args = MagicMock()
    args.reason = 'all'
    args.json = False
    args.verbose = True
    with patch('lib.commands.cmd_dropped.load_cfg', return_value=cfg):
        cmd_dropped(args)
    out = capsys.readouterr().out
    assert 'abc123' in out


# ── cmd_report ────────────────────────────────────────────────────────────────
def test_cmd_report_runs(tmp_path, capsys):
    from lib.commands.cmd_report import cmd_report
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['cache_dir'])
    os.makedirs(cfg['paths']['output_dir'])
    os.makedirs(cfg['paths']['work_dir'])
    # Write minimal cache files that st07_report.run() needs
    _write(os.path.join(cfg['paths']['cache_dir'], 'relevant_commits.json'), [])
    _write(os.path.join(cfg['paths']['cache_dir'], 'filtered_commits.json'), [])
    _write(os.path.join(cfg['paths']['cache_dir'], 'compiled_rules.json'), {
        'schema_hash': 'test', 'rules': {}, 'profiles': {}
    })
    args = MagicMock()
    args.format = None
    args.config = 'test.yaml'
    cfg['reports'] = {'outputs': ['csv'], 'title': 'Test', 'top_n': 0}
    with patch('lib.commands.cmd_report.load_cfg', return_value=cfg):
        cmd_report(args)
    out = capsys.readouterr().out
    assert 'Reports written' in out
