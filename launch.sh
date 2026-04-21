#!/bin/sh
set -e
CFG=${1:-./configs/example-qcom-tcu-default.json}
if [ -z "$TOOLDIR" ]; then
  echo "ERROR: TOOLDIR must be set in the shell environment before running launch.sh" >&2
  exit 1
fi
if [ -z "$WORKSPACE" ]; then
  echo "ERROR: WORKSPACE must be set in the shell environment before running launch.sh" >&2
  exit 1
fi
./run_pipeline.sh "$CFG"
WORK_DIR=$(python3 -c 'import sys; from lib.config import load_config; cfg=load_config(sys.argv[1]); print(cfg.get("project",{}).get("work_dir","./work"))' "$CFG")
python3 ./tools/generate_html_summary.py --work-dir "$WORK_DIR"
echo "Pipeline finished. Review outputs under $WORK_DIR/output"
