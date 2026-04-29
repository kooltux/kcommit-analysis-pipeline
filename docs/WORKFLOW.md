# Workflow Guide

## Quick start

```bash
# 1. Copy the example config
cp configs/example-arm-embedded-full.json /path/to/myproduct/config.json

# 2. Edit the config — set kernel.source_dir, kernel.rev_old/rev_new,
#    kernel.build_dir, project.work_dir, and profiles.active

# 3. Run the full pipeline
python3 kcommit_pipeline.py --config /path/to/myproduct/config.json

# 4. Open the report
xdg-open <work_dir>/output/summary.html
```

## Restarting a stage

Every stage writes a completion flag to `<work_dir>/pipeline_state.json`.
A completed stage is skipped on the next run unless forced.

```bash
# Re-run stage 5 only (scoring)
python3 kcommit_pipeline.py --config cfg.json --stage 5
python3 kcommit_pipeline.py --config cfg.json --stage score_commits

# Re-run from stage 4 onwards (wipes cache/filtered_commits.json and
# all downstream caches)
python3 kcommit_pipeline.py --config cfg.json --from 4

# Force re-run of a completed stage
python3 kcommit_pipeline.py --config cfg.json --stage 6 --force
```

## Typical iteration cycles

### Tuning rules (most common)

Edit rule keyword/path lists in your config repo, then re-run from stage 5:

```bash
# Rules changed → re-score and re-report
python3 kcommit_pipeline.py --config cfg.json --from 5
```

### Tuning the pre-filter

Edit profile `path_blacklist.txt` or `commit_blacklist.txt`, then re-run
from stage 4 (which rewrites `filtered_commits.json`):

```bash
python3 kcommit_pipeline.py --config cfg.json --from 4
```

### Changing the revision range

```bash
python3 kcommit_pipeline.py --config cfg.json --from 1 \
    --override '{"kernel":{"rev_old":"v4.14.280","rev_new":"v4.14.336"}}'
```

Or update `kernel.rev_old`/`kernel.rev_new` in the config file and re-run
`--from 1` (full re-collect required).

### CI/CD — injecting the revision range at build time

```bash
python3 kcommit_pipeline.py \
    --config ${CONFIGDIR}/config.json \
    --override "{\"kernel\":{\"rev_old\":\"${OLD_TAG}\",\"rev_new\":\"${NEW_TAG}\"}}"
```

## Stage input/output map

| Stage | Reads | Writes |
|-------|-------|--------|
| 0 | config | `cache/compiled_rules.json`, `cache/prepare_summary.json` |
| 1 | config, git | `cache/commits.json` |
| 2 | config, build dir | `cache/build_context.json`, `cache/kbuild_static_map.json` |
| 3 | config, build_context | `cache/product_map.json` |
| **4** | commits.json, product_map.json | **`cache/filtered_commits.json`** |
| 5 | filtered_commits.json | `cache/scored_commits.json` |
| 6 | scored_commits.json | `output/*` |

## Dry run

Validate the config and print resolved paths without executing anything:

```bash
python3 kcommit_pipeline.py --config cfg.json --dry-run
python3 kcommit_pipeline.py --config cfg.json --dry-run \
    --override '{"kernel":{"rev_old":"v4.14.111"}}'
```

Prints: project name, work_dir, source_dir, revision range, kernel config,
build_dir, active profiles, scoring config, collect options, filter options.
Exits 1 if validation fails.
