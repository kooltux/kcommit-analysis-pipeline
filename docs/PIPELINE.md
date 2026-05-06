# Pipeline Internals

## Stage details

### Stage 00 — prepare_pipeline
- Validates configuration and all referenced paths.
- Compiles profile rules into `00_compiled_rules.json` for fast reuse.
- Writes `00_prepare_summary.json` (counts of rules per profile).

### Stage 01 — collect_commits
- Runs `git log <rev_old>..<rev_new>` with `--name-only` (and optionally
  `--numstat`, `--no-merges`, `--first-parent`).
- Parses commit metadata: SHA, subject, body, author, timestamps, touched files.
- Outputs `01_commits.json` (and optionally `01_commits.jsonl`).

### Stage 02 — collect_build_context
- Reads the kernel `.config` to extract enabled `CONFIG_*` symbols.
- Scans `build_dir` for compiled `.o`/`.ko` artifacts.
- Parses `kernel_build_log` and `yocto_build_log` for compiled object names.
- Parses DTS roots for device-tree source paths.
- Outputs `02_build_context.json` and `02_kbuild_static_map.json`.

### Stage 03 — build_product_map
- Combines `02_build_context.json` with the static Kbuild map.
- Optionally walks historical Makefiles via `lib/history_map.py` to extend
  the `CONFIG_* → source file` mapping across the revision range.
- Outputs `03_product_map.json` containing:
  - `config_to_paths`: `CONFIG_*` → list of source files
  - `enabled_configs`: enabled symbols from `.config`
  - `built_artifacts_from_dir`, `built_objects_from_log`: build evidence sets

### Stage 04 — prefilter_commits
- Applies the 3-level filter hierarchy (see OVERVIEW.md) to `01_commits.json`.
- Kept commits → `04_filtered_commits.json` (passed to scoring).
- Dropped commits → appended to `04_filtered_commits.json` with `_filter_reason`.
- Also writes `output/filtered_commits.*` (JSON, CSV, HTML, XLSX, ODS).

### Stage 05 — score_commits
- Reads `04_filtered_commits.json`.
- For each commit, evaluates all rules of all active profiles.
- Supports parallel scoring via multiprocessing (`collect.score_workers`).
- Outputs `05_scored_commits.json` with `score`, `matched_profiles`,
  `product_evidence`, and `scoring.profiles` per commit.

### Stage 06 — postfilter_commits
- Sorts scored commits descending by score.
- Drops commits below `filter.min_score` threshold.
- Dropped (low-score) commits get `_filter_reason: "score_below_threshold"`
  and are appended to `04_filtered_commits.json`.
- Assigns final `_rank` (1-based) to kept commits.
- Outputs `06_relevant_commits.json`.

### Stage 07 — report_commits
- Reads `06_relevant_commits.json`.
- Generates all outputs under `<work_dir>/output/`:
  - `relevant_commits.json` / `.csv` / `.xlsx` / `.ods`
  - `summary.html` — interactive report with sortable/filterable table
  - `profile_summary.json` and `profile_matrix.json` / `.csv`
  - `report_stats.json`

## State tracking

Each stage writes its status, timing, and key counters to
`<work_dir>/pipeline_state.json`. The pipeline driver reads this file to
skip already-completed stages (use `--force` to re-run a done stage).

`wipe_downstream()` clears downstream stage outputs when `--from N` is used,
ensuring no stale cache files from a previous run are inadvertently reused.

## Library modules

| Module | Role |
|---|---|
| `lib/config.py` | Comment-aware JSON loader, `${VAR}` expansion |
| `lib/manifest.py` | Reads `VERSION` from `MANIFEST.json` |
| `lib/profile_rules.py` | Profile + rule loading, merging |
| `lib/scoring.py` | `score_commit()`, `precompile_rules()` |
| `lib/html_report.py` | HTML report generator |
| `lib/spreadsheet.py` | XLSX (shared strings) and ODS export |
| `lib/validation.py` | Config validation (full + lightweight) |
| `lib/pipeline_runtime.py` | Stage state tracking, progress display |
| `lib/history_map.py` | Git history → CONFIG_* → path mapping |
| `lib/kbuild.py` | Kbuild/Kconfig static analysis |
| `lib/gitutils.py` | Git subprocess wrappers |
| `lib/patterns.py` | Pattern matching (glob, regex, plain) |
| `lib/parse_kconfig.py` | Kconfig file parser |
