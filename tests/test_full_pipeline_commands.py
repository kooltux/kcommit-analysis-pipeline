"""Realistic small full-pipeline command test.

This test exercises the top-level CLI command flow with a compact but realistic
configuration and small cache/output fixtures. It intentionally calls the same
subcommands a user would run: validate, run, status, dropped, and report.

The setup avoids a real kernel git history by mocking validation and stage
execution, while still using repository-style config files, compiled rules, and
cache payloads.
"""
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from lib.manifest import CACHE_FILES
from lib.pipeline_runtime import init_pipeline_state


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def _sample_commit(sha, score, profiles, reason=None):
    c = {
        'commit': sha,
        'subject': f'fix: {sha[:12]}',
        'author_name': 'Test Dev',
        'author_email': 'dev@example.com',
        'author_time': 1710000000,
        'body': 'Short sample commit body for report details.',
        'files': ['drivers/usb/core.c'],
        'score': score,
        'matched_profiles': profiles,
        'product_evidence': ['config_map:CONFIG_USB'],
        'scoring': {
            'profiles': {p: score if i == 0 else max(score // 4, 1)
                         for i, p in enumerate(profiles)},
            'trace': {'profiles': {}}
        },
    }
    if reason:
        c['_filter_reason'] = reason
    return c


def _compiled_rules():
    empty_rule_body = {
        'keywords_whitelist': [], 'keywords_blacklist': [],
        'path_whitelist': [], 'path_blacklist': [],
        'commit_whitelist': [], 'commit_blacklist': [],
    }
    return {
        'schema_hash': 'test-sentinel-hash',
        'rules': {},
        'profiles': {
            'performance': {
                'description': 'Performance profile',
                'rules': {},
                'merged': empty_rule_body,
            },
            'security_fixes': {
                'description': 'Security fixes profile',
                'rules': {},
                'merged': empty_rule_body,
            },
        },
    }


def _make_cfg(tmp_path):
    root = tmp_path / 'mini-project'
    work = root / 'work'
    cache = root / 'cache'
    out = root / 'output'
    kernel = root / 'kernel'
    kernel.mkdir(parents=True)
    (kernel / '.git').mkdir()
    cfg = {
        'paths': {
            'work_dir': str(work),
            'cache_dir': str(cache),
            'output_dir': str(out),
            'templates_dir': None,
            'profiles_dirs': [os.path.abspath('configs/profiles')],
            'rules_dirs': [os.path.abspath('configs/scoring')],
        },
        'kernel': {
            'source_dir': str(kernel),
            'rev_old': 'v6.0',
            'rev_new': 'v6.1',
            'kernel_config': None,
        },
        'filter': {'min_score': 0},
        'profiles': {'active': {'performance': 100, 'security_fixes': 100}},
        'collect': {},
        'reports': {
            'outputs': ['html', 'csv'],
            'html_detail_mode': 'sidecar',
            'title': 'Mini realistic pipeline test',
            'top_n': 0,
        },
    }
    return cfg


def _seed_cache(cfg):
    cache = cfg['paths']['cache_dir']
    work = cfg['paths']['work_dir']
    os.makedirs(cache, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    init_pipeline_state(os.path.join(work, 'pipeline_state.json'))

    relevant = [
        _sample_commit('a' * 40, 80, ['performance', 'security_fixes']),
        _sample_commit('b' * 40, 35, ['performance']),
    ]
    filtered = [
        _sample_commit('c' * 40, 0, [], reason='path_blacklist'),
    ]

    _write_json(os.path.join(cache, CACHE_FILES['compiled_rules']), _compiled_rules())
    _write_json(os.path.join(cache, CACHE_FILES['relevant']), relevant)
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), filtered)
    _write_json(os.path.join(cache, CACHE_FILES['postfilter_dropped']), [])
    _write_json(os.path.join(cache, CACHE_FILES['scored']), relevant)
    _write_json(os.path.join(cache, CACHE_FILES['commits']), relevant + filtered)
    _write_json(os.path.join(cache, CACHE_FILES['prepare_summary']), {'ok': True})
    _write_json(os.path.join(cache, CACHE_FILES['build_context']), {'kernel_config': [], 'kbuild_files': []})
    _write_json(os.path.join(cache, CACHE_FILES['kbuild_map']), {})
    _write_json(os.path.join(cache, CACHE_FILES['product_map']), {'config_to_paths': {'CONFIG_USB': ['drivers/usb/core.c']}})
    _write_json(os.path.join(cache, CACHE_FILES['prefilter_kept']), relevant)
    return relevant, filtered


def test_full_pipeline_commands_realistic_small(tmp_path, capsys):
    from lib.commands.cmd_validate import cmd_validate
    from lib.commands.cmd_run import cmd_run
    from lib.commands.cmd_status import cmd_status
    from lib.commands.cmd_dropped import cmd_dropped
    from lib.commands.cmd_report import cmd_report

    cfg = _make_cfg(tmp_path)
    relevant, filtered = _seed_cache(cfg)

    validate_args = SimpleNamespace(config='tests/fixtures/full-pipeline-mini.json', override=None)
    with patch('lib.commands.cmd_validate.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_validate.validate_inputs', return_value=([], ['mini realistic test'])):
        cmd_validate(validate_args)
    validate_out = capsys.readouterr().out
    assert 'Configuration OK.' in validate_out

    status_args = SimpleNamespace(config='tests/fixtures/full-pipeline-mini.json', override=None)
    with patch('lib.commands.cmd_status.load_cfg', return_value=cfg):
        cmd_status(status_args)
    status_out = capsys.readouterr().out
    assert 'report_commits' in status_out

    dropped_args = SimpleNamespace(config='tests/fixtures/full-pipeline-mini.json', override=None,
                                   reason='all', json=False, verbose=False)
    with patch('lib.commands.cmd_dropped.load_cfg', return_value=cfg):
        cmd_dropped(dropped_args)
    dropped_out = capsys.readouterr().out
    assert 'path_blacklist' in dropped_out or '1' in dropped_out

    report_args = SimpleNamespace(config='tests/fixtures/full-pipeline-mini.json', override=None,
                                  format=['html,csv'])
    with patch('lib.commands.cmd_report.load_cfg', return_value=cfg):
        cmd_report(report_args)
    report_out = capsys.readouterr().out
    assert 'Reports written to' in report_out
    assert os.path.exists(os.path.join(cfg['paths']['output_dir'], 'relevant_commits.html'))
    assert os.path.exists(os.path.join(cfg['paths']['output_dir'], 'relevant_commits.csv'))

    run_args = SimpleNamespace(config='tests/fixtures/full-pipeline-mini.json', override=None,
                               stage='7', from_=None, resume=False, force=False,
                               progress_json=False)
    with patch('lib.commands.cmd_run.load_cfg', return_value=cfg), \
         patch('lib.commands.cmd_run.run_stage') as mock_run_stage:
        cmd_run(run_args)
    assert mock_run_stage.call_count == 1
    assert mock_run_stage.call_args[0][1] == 'report_commits'

    with open(os.path.join(cfg['paths']['output_dir'], 'relevant_commits.table.json'), encoding='utf-8') as f:
        table_json = json.load(f)
    assert len(table_json) == len(relevant)
    assert table_json[0]['commit'] == 'a' * 40
    assert table_json[0]['matched_profiles'] == ['performance', 'security_fixes']
