"""Tests for lib.commands — cmd_validate, cmd_status, cmd_dropped, cmd_report,
and base helpers (load_state, stage_needs_run, resolve_stage, stage_extra)."""
import json, os, sys
from types import SimpleNamespace
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
    assert stage_needs_run('collect_commits', str(tmp_path), state) is True


def test_stage_needs_run_ok_all_files_exist_legacy(tmp_path):
    """Without base_dirs, files are looked up under work (legacy flat layout)."""
    work = str(tmp_path)
    for rel in (STAGE_OUTPUTS.get('collect_commits') or []):
        full = os.path.join(work, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, 'w').write('{}')
    state = {'collect_commits': {'status': 'ok'}}
    assert stage_needs_run('collect_commits', work, state) is False


def test_stage_needs_run_ok_all_files_exist_with_base_dirs(tmp_path):
    """With base_dirs, 'cache/commits.json' is resolved under cache_dir."""
    cache_dir  = str(tmp_path / 'cache')
    output_dir = str(tmp_path / 'output')
    work       = str(tmp_path / 'work')
    os.makedirs(cache_dir);  os.makedirs(output_dir);  os.makedirs(work)
    base_dirs = {'cache': cache_dir, 'output': output_dir}

    for rel in (STAGE_OUTPUTS.get('collect_commits') or []):
        parts  = rel.split('/', 1)
        prefix = parts[0] if len(parts) == 2 else None
        rest   = parts[1] if len(parts) == 2 else rel
        base   = base_dirs.get(prefix, work)
        full   = os.path.join(base, rest)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, 'w').write('{}')

    state = {'collect_commits': {'status': 'ok'}}
    assert stage_needs_run('collect_commits', work, state, base_dirs=base_dirs) is False


def test_stage_needs_run_missing_cache_file_with_base_dirs(tmp_path):
    """Returns True when cache file is absent even though state says ok."""
    cache_dir  = str(tmp_path / 'cache')
    output_dir = str(tmp_path / 'output')
    work       = str(tmp_path / 'work')
    os.makedirs(cache_dir);  os.makedirs(output_dir);  os.makedirs(work)
    base_dirs = {'cache': cache_dir, 'output': output_dir}
    state = {'collect_commits': {'status': 'ok'}}
    assert stage_needs_run('collect_commits', work, state, base_dirs=base_dirs) is True


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


# ── cmd_run ───────────────────────────────────────────────────────────────────
def _run_args(**kw):
    defaults = dict(config='test.yaml', override=None, stage=None, from_=None,
                    resume=False, force=False, progress_json=False)
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_cmd_run_force_full_pipeline_wipes_state(tmp_path):
    """--force with no --stage/--from must call wipe_downstream starting from stage 0."""
    from lib.commands.cmd_run import cmd_run
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['work_dir'])
    os.makedirs(cfg['paths']['cache_dir'])
    os.makedirs(cfg['paths']['output_dir'])
    args = _run_args(force=True)
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.run_stage'), \
         patch('lib.commands.cmd_run.wipe_downstream') as mock_wipe:
        cmd_run(args)
    mock_wipe.assert_called_once()
    from lib.commands.base import STAGE_ORDER
    assert mock_wipe.call_args[0][1] == STAGE_ORDER[0]


def test_cmd_run_no_force_no_wipe(tmp_path):
    """Plain full run (no --force, --from, --stage) must NOT call wipe_downstream."""
    from lib.commands.cmd_run import cmd_run
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['work_dir'])
    os.makedirs(cfg['paths']['cache_dir'])
    os.makedirs(cfg['paths']['output_dir'])
    args = _run_args(force=False)
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.run_stage'), \
         patch('lib.commands.cmd_run.wipe_downstream') as mock_wipe:
        cmd_run(args)
    mock_wipe.assert_not_called()


def test_cmd_run_force_with_stage_wipes_and_runs_only_target(tmp_path):
    """--force --stage N must wipe N+downstream and run only stage N."""
    from lib.commands.cmd_run import cmd_run
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['work_dir'])
    os.makedirs(cfg['paths']['cache_dir'])
    os.makedirs(cfg['paths']['output_dir'])
    args = _run_args(force=True, stage='0')
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.run_stage') as mock_run, \
         patch('lib.commands.cmd_run.wipe_downstream') as mock_wipe:
        cmd_run(args)
    mock_wipe.assert_called_once()
    mock_run.assert_called_once()


def test_cmd_run_stage_without_force_runs_only_one_stage(tmp_path):
    """--stage N without --force must run only that single stage (no wipe)."""
    from lib.commands.cmd_run import cmd_run
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['work_dir'])
    os.makedirs(cfg['paths']['cache_dir'])
    os.makedirs(cfg['paths']['output_dir'])
    args = _run_args(force=False, stage='6')
    ran_keys = []
    def fake_run_stage(idx, key, fn, cfg, cache, work, state_path, args):
        ran_keys.append(key)
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.run_stage', side_effect=fake_run_stage), \
         patch('lib.commands.cmd_run.wipe_downstream') as mock_wipe:
        cmd_run(args)
    assert ran_keys == ['postfilter_commits']
    mock_wipe.assert_not_called()


def test_cmd_run_wipe_downstream_receives_base_dirs(tmp_path):
    """wipe_downstream must receive base_dirs with realpath-normalised cache and output."""
    from lib.commands.cmd_run import cmd_run
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['work_dir'])
    os.makedirs(cfg['paths']['cache_dir'])
    os.makedirs(cfg['paths']['output_dir'])
    args = _run_args(force=True, stage='0')
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.run_stage'), \
         patch('lib.commands.cmd_run.wipe_downstream') as mock_wipe:
        cmd_run(args)
    call_kwargs = mock_wipe.call_args[1]
    assert 'base_dirs' in call_kwargs
    assert call_kwargs['base_dirs']['cache']  == os.path.realpath(cfg['paths']['cache_dir'])
    assert call_kwargs['base_dirs']['output'] == os.path.realpath(cfg['paths']['output_dir'])


def test_cmd_run_paths_are_normalised(tmp_path):
    """cmd_run must normalise all paths with realpath before passing to stage fns."""
    from lib.commands.cmd_run import cmd_run
    cache_dir = str(tmp_path / 'cache')
    os.makedirs(cache_dir)
    cfg = _minimal_cfg(tmp_path)
    cfg['paths']['cache_dir'] = os.path.join(str(tmp_path), '.', 'cache')
    os.makedirs(cfg['paths']['work_dir'],   exist_ok=True)
    os.makedirs(cfg['paths']['output_dir'], exist_ok=True)
    args = _run_args(force=True, stage='0')
    captured_cfg = {}
    def fake_run_stage(idx, key, fn, c, cache, work, state_path, args):
        captured_cfg.update(c['paths'])
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.wipe_downstream'), \
         patch('lib.commands.cmd_run.run_stage', side_effect=fake_run_stage):
        cmd_run(args)
    assert captured_cfg['cache_dir'] == os.path.realpath(cache_dir)


def test_wipe_downstream_deletes_cache_file(tmp_path):
    """wipe_downstream with base_dirs must delete a cache/ prefixed artifact."""
    from lib.pipeline_runtime import wipe_downstream, init_pipeline_state
    from lib.commands.base import STAGE_ORDER

    state_path = str(tmp_path / 'state.json')
    cache_dir  = str(tmp_path / 'cache')
    output_dir = str(tmp_path / 'output')
    os.makedirs(cache_dir)
    os.makedirs(output_dir)
    init_pipeline_state(state_path)

    artifact = os.path.join(cache_dir, 'commits.json')
    open(artifact, 'w').write('[]')
    assert os.path.exists(artifact)

    outputs = {'collect_commits': ['cache/commits.json']}
    base_dirs = {'cache': cache_dir, 'output': output_dir}
    wipe_downstream(state_path, 'collect_commits', str(tmp_path), outputs,
                    stage_order=STAGE_ORDER, base_dirs=base_dirs)

    assert not os.path.exists(artifact)


def test_wipe_downstream_deletes_output_file(tmp_path):
    """wipe_downstream with base_dirs must delete an output/ prefixed artifact."""
    from lib.pipeline_runtime import wipe_downstream, init_pipeline_state
    from lib.commands.base import STAGE_ORDER

    state_path = str(tmp_path / 'state.json')
    cache_dir  = str(tmp_path / 'cache')
    output_dir = str(tmp_path / 'output')
    os.makedirs(cache_dir)
    os.makedirs(output_dir)
    init_pipeline_state(state_path)

    artifact = os.path.join(output_dir, 'relevant_commits.html')
    open(artifact, 'w').write('<html/>')
    assert os.path.exists(artifact)

    outputs = {'report_commits': ['output/relevant_commits.html']}
    base_dirs = {'cache': cache_dir, 'output': output_dir}
    wipe_downstream(state_path, 'report_commits', str(tmp_path), outputs,
                    stage_order=STAGE_ORDER, base_dirs=base_dirs)

    assert not os.path.exists(artifact)


def test_wipe_downstream_without_base_dirs_legacy(tmp_path):
    """wipe_downstream without base_dirs falls back to work_dir (backward compat)."""
    from lib.pipeline_runtime import wipe_downstream, init_pipeline_state
    from lib.commands.base import STAGE_ORDER

    state_path = str(tmp_path / 'state.json')
    work_dir   = str(tmp_path)
    init_pipeline_state(state_path)

    artifact = os.path.join(work_dir, 'commits.json')
    open(artifact, 'w').write('[]')

    outputs = {'collect_commits': ['commits.json']}
    wipe_downstream(state_path, 'collect_commits', work_dir, outputs,
                    stage_order=STAGE_ORDER)

    assert not os.path.exists(artifact)


def test_cmd_run_resume_uses_base_dirs_for_stage_needs_run(tmp_path):
    """--resume must pass base_dirs to stage_needs_run so cache/ paths resolve correctly."""
    from lib.commands.cmd_run import cmd_run
    cfg = _minimal_cfg(tmp_path)
    os.makedirs(cfg['paths']['work_dir'])
    os.makedirs(cfg['paths']['cache_dir'])
    os.makedirs(cfg['paths']['output_dir'])
    args = _run_args(resume=True)
    captured_base_dirs = {}
    def fake_needs_run(key, work, state, base_dirs=None):
        if base_dirs:
            captured_base_dirs.update(base_dirs)
        return False
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.load_state', return_value={}), \
         patch('lib.commands.cmd_run.stage_needs_run', side_effect=fake_needs_run):
        cmd_run(args)
    assert 'cache'  in captured_base_dirs
    assert 'output' in captured_base_dirs
