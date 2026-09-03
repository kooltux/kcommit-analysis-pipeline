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

### Raw score vs. normalized score

The raw `score` above is **unbounded** and **run-relative**: its magnitude
depends on how many rules fire and their weights, so it is only meaningful when
comparing commits *within the same run*. For readability, each relevant commit
also carries a **normalized score** (column **"Score"**, field `score_norm`):

```
score_norm = round(100 × score / max_score_in_run)     # 0–100
```

`score_norm` is computed in stage 06 against the current run's maximum score.
The raw `score` is kept as **"Score (raw)"** in exports (it preserves absolute
signal strength and ordering fidelity that normalization discards); `score_norm`
is a derived, informational convenience. Like `pick_priority`, it is a
**within-run** value and is not comparable across different runs.

## Author organization

Each commit's **Author** column in the HTML table and spreadsheet exports (CSV,
XLSX, ODS) shows the **Author Organization** — the domain part of the commit's
`author_email` (field: `author_org`). This allows reviewers to quickly identify the
company or entity behind each commit at a glance. The commit-detail pane shows all
author information: **Author** (name), **Author Email**, and **Organization**.
The raw `author_name` and `author_email` fields are also retained in the JSON exports
(`relevant_commits.json`, `filtered_commits.json`).

## Commit size indicators

Independently of scoring, every commit carries two descriptive **size
indicators** that measure how "big" a change is. They are computed in stage 01
from the git `--numstat` data and stored on each commit under the `stats` key:

| Field | Meaning |
|-------|---------|
| `files_changed` | Number of files the commit touches (breadth). Binary files are counted. |
| `insertions`    | Total lines added. |
| `deletions`     | Total lines removed. |
| `lines_changed` | `insertions + deletions` — total churn (depth). |
| `hunks`         | Total number of unified-diff hunks (`@@` blocks) — fragmentation/dispersion. Only populated when `collect.count_hunks` is enabled (see below). |

Three indicators are tracked — **Files Changed** (`files_changed`),
**Lines Changed** (`lines_changed`) and **Hunks** (`hunks`) — because breadth,
depth and dispersion are orthogonal: a one-line fix spread over 50 files, a
2 000-line rewrite of a single file, and a change scattered across 40 tiny
hunks are all "big" in different ways.

They appear as columns in the **spreadsheet exports** (CSV / XLSX / ODS) and in
the **commit-detail Overview** of the HTML report. In the HTML *table* they are
kept as **hidden columns**: their values are still attached to every row (and
remain searchable) but are not shown by default, to keep the table readable now
that the **Complexity** cell (formerly Backport Cx) is the at-a-glance cue in
the table.

These indicators are **purely informational**: they do **not** contribute to
the score, which remains exclusively rule/profile driven. When commits are
collected with `collect.use_name_only` (no per-line deltas), `files_changed`
falls back to the touched-file count and the line totals are `0`.

**Hunks** require patch inspection, which is expensive over a full commit
range. It is therefore **opt-in** via `collect.count_hunks` and computed only
over the *relevant* (post-filter) commits in stage 06. When disabled, `hunks`
is `0`.

## Backport indicators

Beside the relevance score, each **relevant** commit carries three derived
indicators (computed in stage 06) to help triage cherry-pick effort. They are
informational and never affect the score.

| Field | Meaning |
|-------|---------|
| `backport_complexity` | `0–100`, higher = harder to cherry-pick (heuristic estimate). |
| `pick_priority` | `0–100`, higher = look at this first (relevant **and** easy). |
| `cherry_pickable` | `Yes` / `No` / `""` — actual cherry-pick test result onto `kernel.rev_old` (opt-in via `collect.cherry_pick_test`). |

`backport_complexity` is a bounded, weighted blend of commit-shape signals that
correlate with cherry-pick difficulty, with a reduction for commits authored to
be backported (`Cc: stable`, `Fixes:`, CVE), and a hard override for merges:

```
files_pts  = min(25, 25·log2(1+files)  / log2(1+50))     # breadth
lines_pts  = min(30, 30·log2(1+lines)  / log2(1+2000))   # volume/churn
hunks_pts  = min(25, 25·log2(1+hunks)  / log2(1+60))     # fragmentation (0 if disabled)
spread_pts = min(20, 5·(distinct_top_dirs − 1))          # cross-subsystem reach
risk_raw   = files_pts + lines_pts + hunks_pts + spread_pts        # 0..100

friendly   = min(25, 15·has_stable_cc + 10·is_fix + 5·has_cve)
complexity = clamp(0, 100, round(risk_raw − friendly))
if merge commit: complexity = 100
```

`pick_priority` blends **relevance** (`score_norm`, the run-relative normalized
score) with **ease** (`100 − complexity`):

```
score_norm    = round(100 · score / max_score_in_run)
ease          = 100 − complexity
pick_priority = round(0.70·score_norm + 0.30·ease)
```

Relevance dominates (0.70) so a critical-but-hard fix is never buried; ease
(0.30) floats the low-hanging fruit to the top of equally-relevant commits.
Because relevance is normalized against the current run's maximum score,
`pick_priority` is a **within-run ranking aid** and is not comparable across
different runs. The HTML report sorts by `pick_priority` (descending) by
default. Weights are hard-coded.

> These are heuristic estimates from observable commit shape, **not** a real
> cherry-pick trial. A clean estimate does not guarantee a conflict-free pick.
> For definitive answers, enable `collect.cherry_pick_test` to run actual
> `git cherry-pick --no-commit` tests onto `kernel.rev_old`; results appear in
> the `cherry_pickable` column.

In the HTML report the **Complexity** cell (column name; field: `backport_complexity`)
uses a unified 4-level heat scheme (higher = worse / red; lower = easier / green)
for at-a-glance triage. The full set of indicators (Score, files/lines/hunks,
complexity, and pick_priority) is also listed in the commit-detail **Overview**
tab, where Score and Complexity are heat-coloured (higher-better for Score,
higher-worse for Complexity), Pick priority is heat-coloured (higher-better),
and raw Score (raw) is shown uncolored.


## Cherry-pick execution scripts

When `collect.cherry_pick_test` is enabled and `kernel.rev_old` is configured,
stage 07 generates cherry-pick execution files via `lib/cherrypick_script_gen.py`:

| File | Origin | Description |
|------|--------|-------------|
| `output/cherry_pick.sh` | Copied verbatim from `paths.assets_dir` (default: `configs/assets/cherry_pick.sh`) | Static, generic executable script; takes `--set=prefiltered\|relevant` |
| `output/cherry_pick_data.json` | Generated | Run-specific data: `target_rev`, `rev_new`, and the ordered commit list with `relevant` flags |

`cherry_pick.sh` is a **static asset**, never assembled from generated
strings. It is copied byte-for-byte from `paths.assets_dir` into the output
directory (then made executable), so it can be reviewed, diffed, and
shellchecked directly like any other shell script in the repo. `paths.assets_dir`
defaults to the pipeline's own `configs/assets/`, but can be overridden in
your product config (e.g. `"paths": {"assets_dir": "${CONFIGDIR}/assets"}`)
to ship a customized script — for example with extra pre/post hooks —
without forking the pipeline. See `docs/CONFIGURATION.md` for details.

All run-specific values (commit counts, target/new revisions, subjects) are
read at runtime from `cherry_pick_data.json`, which sits next to the script.
The script's `usage()` help text always reports commit counts computed live
from that data file — nothing is hardcoded.

Internally, the script embeds small Python snippets via
`python3 - <<'PYEOF' ... PYEOF` heredocs with a **quoted** delimiter, so bash
never expands or reinterprets anything inside them; the JSON path and any
other values are passed in as real `sys.argv` entries instead of being
interpolated into the Python source text. This keeps Python fully usable
inside the script without any bash/Python nested-quoting issues (verified
with commit subjects containing parentheses and both quote styles).

Only commits with a cached cherry-pick test result of `ok=True` in the
SQLite `CherryDB` for `kernel.rev_old` are included in the data file — the
same database filled by stage 05's cherry-pick enrichment, or refreshed on
demand with the `cp-check` subcommand. Untested and conflicting commits are
omitted from the commit list entirely.

Commits are ordered by **git history** (oldest → newest), independent of the
score/rank ordering used in the reports themselves — `relevant_commits.json`
is sorted by `pick_priority`/score, not chronological order. The order is
re-derived directly from `git rev-list --reverse` at generation time.

```bash
# Show help (commit counts computed live from cherry_pick_data.json)
./output/cherry_pick.sh --help

# Apply every cherry-pickable relevant commit, oldest first
./output/cherry_pick.sh --set=relevant

# Apply all cherry-pickable prefiltered commits
./output/cherry_pick.sh --set=prefiltered

# Target a git repo other than the current directory
./output/cherry_pick.sh --set=relevant --git-dir /path/to/kernel

# On conflict, git cherry-pick stops; resolve then:
git cherry-pick --continue
# or abandon the whole sequence:
git cherry-pick --abort
```

Generation is best-effort and non-fatal: if it fails for any reason, the
report stage still completes and a warning is logged.


### Profile colour legend

Each scoring profile is assigned a deterministic colour (hashed from its name,
kept clear of the red/orange/green/lime heat-pill palette). The left pane's **Scoring
profiles** section shows a legend of labelled coloured bullets, and the table's
**Profiles** column shows the matching bullets for each commit (hover for the
profile name) so multi-profile matches read at a glance without widening the
column.

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
| `output/rule_trace.json`         | Per-commit × per-rule match trace (JSON; always written) |
| `output/rule_trace.csv`          | Per-commit × per-rule match trace (CSV; written when CSV output is enabled) |
| `output/prefilter_debug.json`    | Per-dropped-commit debug detail from stage 04 (copied from cache when present) |
| `output/report_stats.json`       | Pipeline run statistics and generated file list |
| `output/cherry_pick.sh` | Cherry-pick script, copied from `paths.assets_dir` (only when `collect.cherry_pick_test` is enabled) |
| `output/cherry_pick_data.json` | Cherry-pick data file with commits and `relevant` flags (only when `collect.cherry_pick_test` is enabled) |

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

Stage 04 writes `prefilter_kept_commits.json` (kept), `filtered_commits.json`
(prefilter drops), and `prefilter_debug.json` (per-dropped-commit debug detail
and reason-count summary).
Stage 05 scores only `prefilter_kept_commits.json` and writes `scored_commits.json`.
Stage 06 writes `relevant_commits.json`, `postfilter_dropped_commits.json`, and
`postfilter_debug.json` (score distribution and threshold-drop summary).
Stage 07 reads the stage caches and merges dropped lists only when generating
filtered report outputs.

Configuration rejects unknown top-level sections and validates known section keys/types.


## End-to-end command test

A realistic small command-flow regression test lives in `tests/test_full_pipeline_commands.py`. It uses repository-style configuration, sample cache files, and the real command handlers (`validate`, `run`, `status`, `dropped`, `report`) while keeping fixtures intentionally compact.

- `tests/test_full_pipeline_with_mini_inputs.py` uses miniature files stored under `tests/mini-sample/mini-kernel`, `tests/mini-sample/profiles`, and `tests/mini-sample/rules`, plus a dedicated `tests/mini-sample/configs/test-mini.json` config, to exercise early stages and command/report flow with test-local assets.


## Testing

### Running the test suite

The project includes a comprehensive test suite covering all pipeline stages,
utilities, and integration scenarios.

**Using the `run_tests` script (recommended):**

```bash
# From the project root directory
./run_tests
```

The `run_tests` script automatically sets the `WORKSPACE` environment variable
to the current directory and invokes `python3 -m pytest` with the correct paths.

**Manual invocation:**

```bash
# Set WORKSPACE and run all tests
export WORKSPACE=$(pwd)
python3 -m pytest tests/ -v --tb=short

# Run a specific test file
python3 -m pytest tests/test_st07_report.py -v

# Run tests matching a pattern
python3 -m pytest tests/ -k "cherry" -v

# Run with coverage (requires pytest-cov)
python3 -m pytest tests/ --cov=lib --cov-report=term-missing
```

### Test structure

| Test file | Coverage |
|-----------|----------|
| `tests/test_st00_prepare.py` | Stage 00: config validation, profile/rule compilation |
| `tests/test_st01_collect_run.py` | Stage 01: commit collection, numstat parsing |
| `tests/test_st02_build_context.py` | Stage 02: Kconfig parsing, build artifact collection |
| `tests/test_st03_product_map.py` | Stage 03: Kconfig → source path mapping |
| `tests/test_st04_prefilter_run.py` | Stage 04: whitelist/blacklist filtering logic |
| `tests/test_st05_score_run.py` | Stage 05: scoring engine, profile weights |
| `tests/test_st06_postfilter.py` | Stage 06: threshold filtering, backport indicators |
| `tests/test_st07_report.py` | Stage 07: report generation, cherry-pick scripts |
| `tests/test_cherrypick_script_gen.py` | Cherry-pick asset copy + data generation (v19.5.0), incl. `paths.assets_dir` override and end-to-end script execution |
| `tests/test_config.py` | Config loading, path resolution (incl. `paths.assets_dir` default/override) |
| `tests/test_full_pipeline_commands.py` | End-to-end command handlers |
| `tests/test_full_pipeline_with_mini_inputs.py` | Integration tests with mini fixtures |
| `tests/test_*.py` (other files) | Utilities, schema validation, scoring extras |

### Test fixtures

The test suite uses several fixture directories:

- `tests/mini-sample/` — minimal kernel tree and config for integration tests
- `tests/sample-cache/` — pre-generated cache files for stage tests
- `tests/fixtures/` — shared test data and helper utilities

### Continuous integration

All tests must pass before committing. The test count is tracked in the
changelog.

See `CHANGELOG.md` for version history and per-release test counts.
