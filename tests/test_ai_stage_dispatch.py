"""Stage registration and opt-in dispatch of AI preparation."""
from argparse import Namespace

from lib.commands import cmd_run as run_module
from lib.stages import STAGES


def args(**changes):
    value = dict(config='test.json', override=None, stage=None, from_=None,
                 resume=False, force=False, progress_json=False, ai=False)
    value.update(changes)
    return Namespace(**value)

def test_optional_stage_registered_last():
    assert len(STAGES) == 9
    assert STAGES[-1][0] == 'prepare_ai_analysis'

def test_default_run_omits_ai_stage(tmp_path, monkeypatch):
    paths = {name: str(tmp_path / name) for name in ('work_dir', 'cache_dir', 'output_dir')}
    monkeypatch.setattr(run_module, 'load_cfg', lambda *_: {'paths': paths})
    seen = []
    monkeypatch.setattr(run_module, 'run_stage', lambda idx, key, *rest: seen.append(key))
    run_module.cmd_run(args())
    assert seen == [key for key, _ in STAGES[:-1]]

def test_ai_run_includes_ai_stage(tmp_path, monkeypatch):
    paths = {name: str(tmp_path / name) for name in ('work_dir', 'cache_dir', 'output_dir')}
    monkeypatch.setattr(run_module, 'load_cfg', lambda *_: {'paths': paths})
    seen = []
    monkeypatch.setattr(run_module, 'run_stage', lambda idx, key, *rest: seen.append(key))
    run_module.cmd_run(args(ai=True))
    assert seen == [key for key, _ in STAGES]
