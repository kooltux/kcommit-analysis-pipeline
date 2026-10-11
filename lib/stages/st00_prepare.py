"""Stage 00 logic: compile rules and validate configuration.

v20.2.0: reports milestone progress through update_stage_progress() so that the
stage shows a bar (validation, rule compilation, cache writing).
"""
import os
from lib.config import save_json
from lib.manifest import CACHE_FILES, NSTAGES, VERSION
from lib.pipeline_runtime import finish_progress_line, update_stage_progress
from lib.profile_rules import compile_rules_for_config, active_profile_names
from lib.validation import validate_inputs


def run(cfg, cache):
    update_stage_progress(0, NSTAGES, 0.05, 'validating configuration')
    problems, notices = validate_inputs(cfg)
    for n in notices:
        print(f'  NOTICE: {n}')
    if problems:
        for p in problems:
            print(f'  ERROR:  {p}')
        raise SystemExit(2)

    update_stage_progress(0, NSTAGES, 0.20, 'compiling profiles and rules')
    compiled = compile_rules_for_config(cfg, cache_dir=cache)
    update_stage_progress(0, NSTAGES, 0.85, 'saving compiled rules')
    save_json(os.path.join(cache, CACHE_FILES['compiled_rules']), compiled)

    names   = active_profile_names(cfg)
    summary = {
        'pipeline_version': VERSION,
        'profiles': names,
        'rule_counts': {
            pname: len((compiled.get(pname) or {}).get('rules', {}))
            for pname in names
        },
    }
    update_stage_progress(0, NSTAGES, 0.95, 'writing summary')
    save_json(os.path.join(cache, CACHE_FILES['prepare_summary']), summary)
    update_stage_progress(0, NSTAGES, 1.0, 'prepared')
    finish_progress_line()
    return summary
