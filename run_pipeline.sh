#!/bin/sh
set -e
CFG=${1:?usage: ./run_pipeline.sh <config.json>}
STATE=$(python3 -c 'import sys; from lib.config import load_config; cfg=load_config(sys.argv[1]); print(cfg.get("project",{}).get("work_dir","./work") + "/pipeline_state.json")' "$CFG")
TOTAL=6
python3 -c 'from lib.pipeline_runtime import save_state; save_state("'"$STATE"'", {"stages": []})'
python3 01_collect_commits.py --config "$CFG"
python3 02_collect_build_context.py --config "$CFG"
python3 03_build_product_map.py --config "$CFG"
python3 04_enrich_commits.py --config "$CFG"
python3 05_score_commits.py --config "$CFG"
python3 06_report_commits.py --config "$CFG"
