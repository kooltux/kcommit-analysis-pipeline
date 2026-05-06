"""Stage 00 logic: compile rules and validate configuration."""
import os
from lib.config import save_json
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

    compiled = compile_rules_for_config(cfg)
    save_json(os.path.join(cache, '00_compiled_rules.json'), compiled)

    names   = active_profile_names(cfg)
    summary = {
        'active_profiles': names,
        'rule_counts': {
            pname: len((compiled.get(pname) or {}).get('rules', {}))
            for pname in names
        },
    }
    save_json(os.path.join(cache, '00_prepare_summary.json'), summary)
    return summary
