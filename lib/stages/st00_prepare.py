"""Stage 00 logic: compile rules and validate configuration."""
import os
from lib.config import save_json
from lib.manifest import CACHE_FILES
from lib.profile_rules import compile_rules_for_config, active_profile_names
from lib.validation import validate_inputs


def run(cfg, cache):
    problems, notices = validate_inputs(cfg)
    for n in notices:
        print(f'  NOTICE: {n}')
    if problems:
        for p in problems:
            print(f'  ERROR:  {p}')
        raise SystemExit(2)

    compiled = compile_rules_for_config(cfg, work_dir=cache)
    save_json(os.path.join(cache, CACHE_FILES['compiled_rules']), compiled)

    names   = active_profile_names(cfg)
    summary = {
        'profiles': names,
        'rule_counts': {
            pname: len((compiled.get(pname) or {}).get('rules', {}))
            for pname in names
        },
    }
    save_json(os.path.join(cache, CACHE_FILES['prepare_summary']), summary)
    return summary
