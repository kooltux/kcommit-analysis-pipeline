# kcommit-analysis-pipeline

A restartable pipeline to analyse Linux kernel commits between two revisions
and identify those relevant to a given embedded product, scored exclusively
through configurable profile/rule sets.

## What it does

The pipeline compares two kernel revisions, collects the commit history,
gathers product-specific build context (Kconfig, build logs, DTS), maps
enabled Kconfig symbols to source paths, pre-filters irrelevant commits, scores
the remainder through profiles and rules, and generates HTML, CSV, XLSX, and
ODS reports for manual review.

## Pipeline stages

| # | Key | Stage module | Purpose |
|---|------------------------|--------------------------------------|------------------------------------------------------|
| 0 | `prepare_pipeline`      | `lib/stages/st00_prepare.py`       | Validate config, compile profiles/rules |
| 1 | `collect_commits`       | `lib/stages/st01_collect.py`       | Collect commit metadata from `git log` |
| 2 | `collect_build_context` | `lib/stages/st02_build_context.py` | Collect kernel `.config`, build artifacts, logs |
| 3 | `build_product_map`     | `lib/stages/st03_product_map.py`   | Map `CONFIG_*` symbols → source paths |
| 4 | `prefilter_commits`     | `lib/stages/st04_prefilter.py`     | Drop commits that cannot possibly score |
| 5 | `score_commits`         | `lib/stages/st05_score.py`         | Score commits via active profiles and rules |
| 6 | `postfilter_commits`    | `lib/stages/st06_postfilter.py`    | Drop commits below score threshold |
| 7 | `report_commits`        | `lib/stages/st07_report.py`        | Generate CSV / JSON / HTML / XLSX / ODS reports |

Intermediate data is stored in `<work_dir>/cache/` and each stage can be
restarted independently.

## Running the pipeline

```bash
# Run all stages
python3 kcommit_pipeline.py run --config /path/to/cfg.json

# Run a single stage
python3 kcommit_pipeline.py run --config /path/to/cfg.json --stage 5

# Re-run from stage 4 onwards (wipes downstream cache)
python3 kcommit_pipeline.py run --config /path/to/cfg.json --from 4

# Resume: skip already-completed stages
python3 kcommit_pipeline.py run --config /path/to/cfg.json --resume

# Validate config without running
python3 kcommit_pipeline.py validate --config /path/to/cfg.json

# Show stage completion status
python3 kcommit_pipeline.py status --config /path/to/cfg.json

# Re-generate reports from cached scored data
python3 kcommit_pipeline.py report --config /path/to/cfg.json --format html --format xlsx

# Inspect filtered-out commits
python3 kcommit_pipeline.py dropped --config /path/to/cfg.json --reason prefilter

# Override config values at runtime (deep-merged into loaded config)
python3 kcommit_pipeline.py run --config /path/to/cfg.json \
    --override '{"kernel":{"rev_old":"v6.1.1"}}'

# Machine-readable progress events (one JSON line per stage)
python3 kcommit_pipeline.py run --config /path/to/cfg.json --progress-json
```

## Scoring model

Scoring is **exclusively through profiles and rules**. Kernel annotation
metadata (CVE, Fixes, Cc:stable, Syzbot) is extracted and displayed as badges
in the HTML report but does **not** add to the score.

```
for each active profile P with weight W (0–100):
    rule_sum  = sum(rule.weight for matching rules), capped at 100
    score[P]  = int(rule_sum × W / 100)

total_score = Σ score[P]
```

The only way to influence scoring is through **profile weights**
(`profiles.active`) and **rule weights** in each rule-set directory.

## Pre-scoring filter (stage 04)

Before scoring, stage 04 drops structurally irrelevant commits in priority order:

1. SHA in `commit_whitelist` → **FORCE-KEEP**
2. SHA in `commit_blacklist` → **FORCE-DROP**
3. ALL touched files in `path_blacklist` → **DROP**
4. ANY touched file in `path_whitelist` → **KEEP**
5. Kconfig/build-artifact coverage check (optional) → **DROP** if uncovered
6. ANY keyword in `keywords_whitelist` → **KEEP**
7. ANY keyword in `keywords_blacklist` → **DROP**
8. Default → **KEEP**

## Configuration

See `docs/CONFIGURATION.md` for the full reference.

Key sections:

```json
{
  "kernel":  { "source_dir": "…", "rev_old": "v6.1", "rev_new": "v6.6" },
  "profiles": {
    "active": {
      "my_profile_a": 100,
      "my_profile_b": 70
    }
  },
  "filter":  { "enabled": true, "min_score": 10 }
}
```

## Profiles and rules

Profiles and rules live in directories referenced by `paths.profiles_dirs`
and `paths.rules_dirs` (defaulting to `<CONFIGDIR>/profiles/` and
`<CONFIGDIR>/rules/`). The singular compatibility aliases `profiles_dir` and
`rules_dir` are also accepted and normalized to the same internal list form.
When a requested profile or rule is not found in the external config tree, the
pipeline automatically falls back to the built-in shipped `configs/profiles/`
and `configs/rules/` directories. See `docs/PROFILES_AND_RULES.md` for the
full format.

## Outputs

| File | Description |
|------|-------------|
| `output/relevant_commits.html`   | Interactive HTML report (filters, sort, CSV export, commit detail view) |
| `output/relevant_commits.csv`    | Ranked commits above the score threshold |
| `output/relevant_commits.json`   | Same data as JSON |
| `output/filtered_commits.html`   | Dropped commits with filter reason (HTML) |
| `output/filtered_commits.csv`    | Dropped commits with filter reason (CSV) |
| `output/filtered_commits.json`   | Dropped commits with filter reason (JSON) |
| `output/profile_summary.json`    | Per-profile commit count and average score |
| `output/profile_matrix.json`     | Per-commit × per-profile score breakdown (JSON) |
| `output/profile_matrix.csv`      | Per-commit × per-profile score breakdown (CSV) |
| `output/report_stats.json`       | Pipeline run statistics and generated file list |
| `output/rule_trace.json`         | Per-commit × per-rule scoring trace (JSON) |

Optional XLSX/ODS: enable with `"reports": { "outputs": ["xlsx", "ods"] }`.
Each enabled format produces both `relevant_commits.*` and `filtered_commits.*`
counterparts, plus `profile_summary.*`, `profile_matrix.*`, and workbook outputs when those formats are enabled.

## Requirements

- Python 3.13+
- `git` on `PATH`
- `openpyxl` for XLSX output (`pip install openpyxl`)

## Example config

`configs/example-arm-embedded-full.json` — fully annotated example with all
available options documented.


## Cache contract

Stage 04 writes `prefilter_kept_commits.json` (kept) and `filtered_commits.json` (dropped).
Stage 05 scores only `prefilter_kept_commits.json`.
Stage 06 writes `relevant_commits.json` and `postfilter_dropped_commits.json`.
Stage 07 merges dropped lists for report outputs only.

Configuration rejects unknown top-level sections and validates known section keys/types.


## End-to-end command test

A realistic small command-flow regression test lives in `tests/test_full_pipeline_commands.py`. It uses repository-style configuration, sample cache files, and the real command handlers (`validate`, `run`, `status`, `dropped`, `report`) while keeping fixtures intentionally compact.

- `tests/test_full_pipeline_with_mini_inputs.py` uses miniature files stored under `tests/mini-sample/mini-kernel`, `tests/mini-sample/profiles`, and `tests/mini-sample/rules`, plus a dedicated `tests/mini-sample/configs/test-mini.json` config, to exercise early stages and command/report flow with test-local assets.
