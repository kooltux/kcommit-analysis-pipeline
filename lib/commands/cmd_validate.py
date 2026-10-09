"""kcommit-analysis-pipeline — cmd_validate subcommand."""
import logging

from lib.commands.base import load_cfg
from lib.manifest import VERSION
from lib.validation import validate_inputs


def cmd_validate(args):
    # v20.1.0: include/variable/JSON errors are reported as validation problems
    # (exit 1, no traceback); built-in variable errors keep their SystemExit.
    try:
        cfg = load_cfg(args)
    except (OSError, ValueError) as exc:
        logging.error('%s', exc)
        raise SystemExit(1)
    work     = cfg['paths']['work_dir']
    kernel   = cfg.get('kernel', {}) or {}
    filt     = cfg.get('filter', {}) or {}
    profiles = (cfg.get('profiles', {}) or {}).get('active') or []

    print(f'=== kcommit-analysis-pipeline {VERSION} — validate ===')
    print(f'Config   : {args.config}')
    print(f'Work dir : {work}')
    print(f'Repo     : {kernel.get("source_dir","N/A")}')
    print(f'Range    : {kernel.get("rev_old","?")} .. {kernel.get("rev_new","?")}')
    print(f'Filter   : {filt}')
    if isinstance(profiles, dict):
        for pn, pw in profiles.items():
            print(f'  profile: {pn} (weight {pw})')
    problems, notices = validate_inputs(cfg)
    for n in notices:
        print(f'  NOTICE: {n}')
    if problems:
        for p in problems:
            logging.error('%s', p)
        raise SystemExit(1)
    print('Configuration OK.')


# ── Sub-command: report (E.10) ────────────────────────────────────────────────
