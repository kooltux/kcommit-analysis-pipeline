import json
import os
from unittest.mock import MagicMock, patch

import pytest

from lib.commands.base import emit_progress, run_stage, stage_extra
from lib.pipeline_runtime import StageResult, init_pipeline_state


def _cfg(tmp_path):
    return {
        'paths': {
            'work_dir': str(tmp_path / 'work'),
            'cache_dir': str(tmp_path / 'cache'),
            'output_dir': str(tmp_path / 'output'),
            'templates_dir': None,
        }
    }


def test_emit_progress_includes_pct_and_extra(capsys):
    emit_progress(3, 'score_commits', 'running', pct=55, extra={'x': 1})
    out = capsys.readouterr().out.strip()
    obj = json.loads(out)
    assert obj['stage'] == 3
    assert obj['pct'] == 55
    assert obj['x'] == 1


def test_stage_extra_stage_result_passthrough():
    sr = StageResult(extra={'foo': 1, 'bar': 2})
    assert stage_extra('anything', sr, 0.1) == {'foo': 1, 'bar': 2}


def test_stage_extra_prepare_pipeline_profiles():
    extra = stage_extra('prepare_pipeline', {'profiles': ['a', 'b', 'c']}, 0.1)
    assert extra == {'profile_count': 3}


def test_stage_extra_postfilter_commits():
    extra = stage_extra('postfilter_commits', ([1, 2], [3], 7.5), 0.2)
    assert extra['output_count'] == 2
    assert extra['dropped_count'] == 1
    assert extra['min_score'] == 7.5


def test_stage_extra_report_commits():
    extra = stage_extra('report_commits', {'total_scored_commits': 9}, 0.1)
    assert extra == {'total_scored_commits': 9}


def test_run_stage_skips_when_done_and_progress_json(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    os.makedirs(cfg['paths']['work_dir'], exist_ok=True)
    os.makedirs(cfg['paths']['cache_dir'], exist_ok=True)
    os.makedirs(cfg['paths']['output_dir'], exist_ok=True)
    state_path = os.path.join(cfg['paths']['work_dir'], 'pipeline_state.json')
    init_pipeline_state(state_path)
    state = {'collect_commits': {'status': 'ok'}}
    args = MagicMock(force=False, resume=False, progress_json=True)
    with patch('lib.commands.base.is_stage_done', return_value=True):
        run_stage(1, 'collect_commits', lambda cfg, cache: [], cfg, cfg['paths']['cache_dir'], cfg['paths']['work_dir'], state_path, args)
    obj = json.loads(capsys.readouterr().out.strip())
    assert obj['status'] == 'skipped'


def test_run_stage_failure_with_progress_json(tmp_path, capsys):
    cfg = _cfg(tmp_path)
    os.makedirs(cfg['paths']['work_dir'], exist_ok=True)
    os.makedirs(cfg['paths']['cache_dir'], exist_ok=True)
    os.makedirs(cfg['paths']['output_dir'], exist_ok=True)
    state_path = os.path.join(cfg['paths']['work_dir'], 'pipeline_state.json')
    init_pipeline_state(state_path)
    args = MagicMock(force=False, resume=False, progress_json=True)

    def boom(cfg, cache):
        raise RuntimeError('boom')

    with pytest.raises(SystemExit):
        run_stage(1, 'collect_commits', boom, cfg, cfg['paths']['cache_dir'], cfg['paths']['work_dir'], state_path, args)
    lines = [json.loads(x) for x in capsys.readouterr().out.strip().splitlines() if x.strip()]
    assert lines[0]['status'] == 'running'
    assert lines[-1]['status'] == 'failed'
    assert lines[-1]['error'] == 'boom'


def test_cmd_run_resume_no_pending(tmp_path, capsys):
    from lib.commands.cmd_run import cmd_run
    cfg = _cfg(tmp_path)
    args = MagicMock(config='x', override=None, stage=None, from_=None, resume=True, force=False, progress_json=False)
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.load_state', return_value={}), \
         patch('lib.commands.cmd_run.stage_needs_run', return_value=False):
        cmd_run(args)
    out = capsys.readouterr().out
    assert 'nothing to do' in out.lower()


def test_cmd_run_stage_force_wipes_downstream(tmp_path):
    from lib.commands.cmd_run import cmd_run
    cfg = _cfg(tmp_path)
    args = MagicMock(config='x', override=None, stage='0', from_=None, resume=False, force=True, progress_json=False)
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.resolve_stage', return_value=(0, 'prepare_pipeline')), \
         patch('lib.commands.cmd_run.wipe_downstream') as wipe, \
         patch('lib.commands.cmd_run.run_stage') as run_stage_mock:
        cmd_run(args)
    wipe.assert_called_once()
    run_stage_mock.assert_called_once()


def test_cmd_status_prints_generated_report_files(tmp_path, capsys):
    from lib.commands.cmd_status import cmd_status
    cfg = _cfg(tmp_path)
    work = cfg['paths']['work_dir']
    os.makedirs(os.path.join(work, 'output'), exist_ok=True)
    with open(os.path.join(work, 'output', 'report_stats.json'), 'w', encoding='utf-8') as f:
        json.dump({'generated_files': ['relevant_commits.html', 'summary.xlsx']}, f)
    args = MagicMock(config='x', override=None)
    with patch('lib.commands.cmd_status.load_cfg', return_value=cfg):
        cmd_status(args)
    out = capsys.readouterr().out
    assert 'Last report run' in out
    assert 'relevant_commits.html' in out
