"""Stage registry for kcommit-analysis-pipeline.

Single source of truth for stage ordering, keys, and run functions.
kcommit_pipeline.py imports STAGES and NSTAGES from here.
"""
from lib.stages.st00_prepare       import run as run_st00
from lib.stages.st01_collect       import run as run_st01
from lib.stages.st02_build_context import run as run_st02
from lib.stages.st03_product_map   import run as run_st03
from lib.stages.st04_prefilter     import run as run_st04, write_outputs as prefilter_write_outputs
from lib.stages.st05_score         import run as run_st05
from lib.stages.st06_postfilter    import run as run_st06
from lib.stages.st07_report        import run as run_st07

# Each entry: (pipeline_state_key, run_function)
# Order defines execution sequence.
STAGES = [
    ('prepare_pipeline',      run_st00),
    ('collect_commits',       run_st01),
    ('collect_build_context', run_st02),
    ('build_product_map',     run_st03),
    ('prefilter_commits',     run_st04),
    ('score_commits',         run_st05),
    ('postfilter_commits',    run_st06),
    ('report_commits',        run_st07),
]

NSTAGES = len(STAGES)

__all__ = [
    'STAGES', 'NSTAGES',
    'run_st00','run_st01','run_st02','run_st03',
    'run_st04','run_st05','run_st06','run_st07',
    'prefilter_write_outputs',
]
