"""kcommit-analysis-pipeline — cmd_status subcommand."""
import os

from lib.commands.base import load_cfg, load_state
from lib.manifest import STAGE_OUTPUTS
from lib.stages import STAGES


def cmd_status(args):
    cfg = load_cfg(args)
    work       = cfg['paths']['work_dir']
    state_path = os.path.join(work, 'pipeline_state.json')
    state      = load_state(state_path)

    print(f'{"#":<3}  {"Key":<30}  {"Status":<10}  Duration')
    print('-' * 70)
    for idx, (key, _fn) in enumerate(STAGES):
        s    = state.get(key, {})
        st   = s.get('status', 'pending')
        dur  = f"{s['duration_sec']:.1f}s" if 'duration_sec' in s else ''
        mark = {'ok': '✓', 'failed': '✗', 'running': '…'}.get(st, ' ')
        print(f'{mark}{idx:<3}  {key:<30}  {st:<10}  {dur}')

    print()
    for key, files in STAGE_OUTPUTS.items():
        for rel in files:
            full = os.path.join(work, rel)
            tag  = '✓' if os.path.exists(full) else '✗'
            print(f'  {tag}  {rel}')

    # D.2: show actual outputs recorded by the last report run
    rs_path = os.path.join(work, 'output', 'report_stats.json')
    if os.path.exists(rs_path):
        try:
            import json as _json
            rs  = _json.loads(open(rs_path, encoding='utf-8').read())
            gen = rs.get('generated_files') or []
            if gen:
                outdir = os.path.join(work, 'output')
                print()
                print('  Last report run — generated files:')
                for rel in gen:
                    tag = '✓' if os.path.exists(os.path.join(outdir, rel)) else '✗'
                    print(f'    {tag}  output/{rel}')
        except Exception:
            pass


# ── Sub-command: validate ─────────────────────────────────────────────────────
