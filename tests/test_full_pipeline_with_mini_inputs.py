"""Miniature end-to-end pipeline/command regression using test-local inputs.

Fixtures live entirely under tests/: a tiny kernel tree, test-only profiles,
rules, and a dedicated config file. The test calls the command handlers and
runs report generation from realistic small cache artifacts while also
exercising early-stage helpers with miniature input files.
"""
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from lib.manifest import CACHE_FILES
from lib.pipeline_runtime import init_pipeline_state
from lib.stages.st00_prepare import run as run_prepare
from lib.stages.st02_build_context import run as run_build_context


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def _sample_commit(sha, score, profiles, reason=None):
    c = {
        'commit': sha,
        'subject': f'usb: fix regression {sha[:8]}',
        'author_name': 'Mini Dev',
        'author_email': 'mini@example.com',
        'author_time': 1710000000,
        'commit_time': 1710000030,
        'body': 'Miniature commit body for command and HTML detail testing.',
        'files': ['drivers/usb/core.c', 'include/linux/usb.h'],
        'numstat': [['1', '0', 'drivers/usb/core.c']],
        'score': score,
        'matched_profiles': profiles,
        'product_evidence': ['config_map:CONFIG_USB'],
        'scoring': {
            'profiles': {p: score if i == 0 else max(score // 2, 1)
                         for i, p in enumerate(profiles)},
            'trace': {'profiles': {}}
        },
    }
    if reason:
        c['_filter_reason'] = reason
    return c


def _cfg_from_fixture(tmp_path):
    from lib.commands.base import load_cfg
    args = SimpleNamespace(config='tests/mini-sample/configs/test-mini.json', override=None)
    cfg = load_cfg(args)
    root = tmp_path / 'runtime'
    cfg['paths']['work_dir'] = str(root / 'work')
    cfg['paths']['cache_dir'] = str(root / 'cache')
    cfg['paths']['output_dir'] = str(root / 'output')
    cfg['kernel']['source_dir'] = os.path.abspath('tests/mini-sample/mini-kernel')
    cfg['kernel']['kernel_config'] = os.path.abspath('tests/mini-sample/mini-kernel/.config')
    cfg['paths']['profiles_dirs'] = [os.path.abspath('tests/mini-sample/profiles')]
    cfg['paths']['rules_dirs'] = [os.path.abspath('tests/mini-sample/rules')]
    cfg['paths']['templates_dir'] = None
    cfg['reports'].pop('html_detail_mode', None)
    return cfg


def _seed_cache(cfg):
    cache = cfg['paths']['cache_dir']
    work = cfg['paths']['work_dir']
    os.makedirs(cache, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    init_pipeline_state(os.path.join(work, 'pipeline_state.json'))

    relevant = [
        _sample_commit('a' * 40, 75, ['mini_performance', 'mini_security']),
        _sample_commit('b' * 40, 30, ['mini_performance']),
    ]
    filtered = [
        _sample_commit('c' * 40, 0, [], reason='path_blacklist'),
    ]
    _write_json(os.path.join(cache, CACHE_FILES['relevant']), relevant)
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), filtered)
    _write_json(os.path.join(cache, CACHE_FILES['postfilter_dropped']), [])
    _write_json(os.path.join(cache, CACHE_FILES['scored']), relevant)
    _write_json(os.path.join(cache, CACHE_FILES['commits']), relevant + filtered)
    return relevant, filtered


def test_full_pipeline_with_mini_inputs(tmp_path, capsys):
    from lib.commands.cmd_validate import cmd_validate
    from lib.commands.cmd_status import cmd_status
    from lib.commands.cmd_dropped import cmd_dropped
    from lib.commands.cmd_report import cmd_report
    from lib.commands.cmd_run import cmd_run

    cfg = _cfg_from_fixture(tmp_path)

    with patch('lib.validation.subprocess.run') as mock_git:
        mock_git.return_value.returncode = 0
        summary = run_prepare(cfg, cfg['paths']['cache_dir'])
    assert 'mini_performance' in summary['profiles']
    assert os.path.exists(os.path.join(cfg['paths']['cache_dir'], CACHE_FILES['compiled_rules']))

    ctx, kmap = run_build_context(cfg, cfg['paths']['cache_dir'])
    assert 'CONFIG_USB=y' in (ctx.get('kernel_config') or [])
    assert isinstance(kmap, dict)

    relevant, filtered = _seed_cache(cfg)

    validate_args = SimpleNamespace(config='tests/mini-sample/configs/test-mini.json', override=None)
    with patch('lib.commands.cmd_validate.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_validate.validate_inputs', return_value=([], ['mini fixture'])):
        cmd_validate(validate_args)
    assert 'Configuration OK.' in capsys.readouterr().out

    status_args = SimpleNamespace(config='tests/mini-sample/configs/test-mini.json', override=None)
    with patch('lib.commands.cmd_status.load_cfg', return_value=cfg):
        cmd_status(status_args)
    assert 'collect_commits' in capsys.readouterr().out

    dropped_args = SimpleNamespace(config='tests/mini-sample/configs/test-mini.json', override=None,
                                   reason='all', json=False, verbose=False)
    with patch('lib.commands.cmd_dropped.load_cfg', return_value=cfg):
        cmd_dropped(dropped_args)
    dropped_out = capsys.readouterr().out
    assert 'path_blacklist' in dropped_out or '1' in dropped_out

    report_args = SimpleNamespace(config='tests/mini-sample/configs/test-mini.json', override=None,
                                  format=['html,csv'])
    with patch('lib.commands.cmd_report.load_cfg', return_value=cfg):
        cmd_report(report_args)
    report_out = capsys.readouterr().out
    assert 'Reports written to' in report_out
    assert os.path.exists(os.path.join(cfg['paths']['output_dir'], 'relevant_commits.html'))
    assert os.path.exists(os.path.join(cfg['paths']['output_dir'], 'relevant_commits.csv'))

    with open(os.path.join(cfg['paths']['output_dir'], 'relevant_commits.table.json'), encoding='utf-8') as f:
        table_rows = json.load(f)
    assert len(table_rows) == len(relevant)
    assert table_rows[0]['commit'] == 'a' * 40
    assert table_rows[0]['matched_profiles'] == ['mini_performance', 'mini_security']

    run_args = SimpleNamespace(config='tests/mini-sample/configs/test-mini.json', override=None,
                               stage='7', from_=None, resume=False, force=False,
                               progress_json=False)
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.run_stage') as mock_run_stage:
        cmd_run(run_args)
    assert mock_run_stage.call_count == 1
    assert mock_run_stage.call_args[0][1] == 'report_commits'
