"""Stage registration and config-driven dispatch of AI preparation (v20.1.0)."""
from argparse import Namespace

import pytest

from lib.commands import cmd_run as run_module
from lib.config import ai_active
from lib.stages import STAGES


def args(**changes):
    value = dict(config='test.json', override=None, stage=None, from_=None,
                 resume=False, force=False, progress_json=False)
    value.update(changes)
    return Namespace(**value)


def _cfg(tmp_path, **extra):
    paths = {name: str(tmp_path / name) for name in ('work_dir', 'cache_dir', 'output_dir')}
    cfg = {'paths': paths}
    cfg.update(extra)
    return cfg


def _run(monkeypatch, cfg, namespace):
    monkeypatch.setattr(run_module, 'load_cfg', lambda *_: cfg)
    seen = []
    monkeypatch.setattr(run_module, 'run_stage', lambda idx, key, *rest: seen.append(key))
    run_module.cmd_run(namespace)
    return seen


def test_optional_stage_registered_last():
    assert len(STAGES) == 9
    assert STAGES[-1][0] == 'prepare_ai_analysis'


@pytest.mark.parametrize('section,expected', [
    (None, False), ({}, True), ({'enabled': True}, True), ({'enabled': False}, False),
    ('invalid', False)])
def test_ai_active(section, expected):
    cfg = {} if section is None else {'ai': section}
    assert ai_active(cfg) is expected


def test_run_without_ai_section_omits_ai_stage(tmp_path, monkeypatch):
    seen = _run(monkeypatch, _cfg(tmp_path), args())
    assert seen == [key for key, _ in STAGES[:-1]]


def test_run_with_disabled_ai_omits_ai_stage(tmp_path, monkeypatch):
    seen = _run(monkeypatch, _cfg(tmp_path, ai={'enabled': False}), args())
    assert seen == [key for key, _ in STAGES[:-1]]


def test_run_with_ai_section_includes_ai_stage(tmp_path, monkeypatch):
    seen = _run(monkeypatch, _cfg(tmp_path, ai={}), args())
    assert seen == [key for key, _ in STAGES]


def test_explicit_stage_8_requires_active_ai(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match='AI is not enabled'):
        _run(monkeypatch, _cfg(tmp_path), args(stage='8'))
    with pytest.raises(SystemExit, match='AI is not enabled'):
        _run(monkeypatch, _cfg(tmp_path, ai={'enabled': False}), args(from_='8'))


def test_explicit_stage_8_runs_when_ai_active(tmp_path, monkeypatch):
    seen = _run(monkeypatch, _cfg(tmp_path, ai={}), args(stage='8'))
    assert seen == ['prepare_ai_analysis']


@pytest.mark.parametrize('ai,expected', [(None, 8), ({'enabled': False}, 8), ({}, 9)])
def test_displayed_stage_total_matches_stages_of_the_run(tmp_path, monkeypatch, ai, expected):
    from lib import pipeline_runtime
    cfg = _cfg(tmp_path) if ai is None else _cfg(tmp_path, ai=ai)
    totals = []
    monkeypatch.setattr(run_module, 'load_cfg', lambda *_: cfg)
    monkeypatch.setattr(run_module, 'run_stage',
                        lambda *rest: totals.append(pipeline_runtime._STAGE_TOTAL))
    run_module.cmd_run(args())
    assert set(totals) == {expected}
    assert len(totals) == expected
    assert pipeline_runtime._STAGE_TOTAL is None


def test_stage_total_override_applies_to_state_and_is_reset(tmp_path):
    from lib import pipeline_runtime as runtime
    state = str(tmp_path / 'state.json')
    runtime.set_stage_total(8)
    try:
        runtime.start_stage(state, 'prepare_pipeline', 0, 9)
    finally:
        runtime.set_stage_total(None)
    assert runtime.get_pipeline_state(state)['stages']['prepare_pipeline']['total'] == 8
    runtime.start_stage(state, 'collect_commits', 1, 9)
    assert runtime.get_pipeline_state(state)['stages']['collect_commits']['total'] == 9


def test_ai_option_is_gone(monkeypatch):
    import sys
    import kcommit_pipeline
    monkeypatch.setattr(sys, 'argv', ['kcommit_pipeline.py', 'run', '--config', 'x.json', '--ai'])
    with pytest.raises(SystemExit) as excinfo:
        kcommit_pipeline.main()
    assert excinfo.value.code == 2
