# Pipeline Internals

## Stage details

### Stage 00 — prepare_pipeline
- Validates configuration and all referenced paths.
- Loads all active profile JSON files and resolves rule directories.
- Compiles rule patterns into `00_compiled_rules.json` (deduplicated: each
  rule body stored once, referenced by name from each profile).
- Writes `00_prepare_summary.json` with active profile names and rule counts.

### Stage 01 — collect_commits
- Runs `git log <rev_old>..<rev_new> --name-only` (optionally `--numstat`,
  `--no-merges`, `--first-parent`).
- Parses commit metadata: SHA, subject, body, author, timestamps, touched files.
- Outputs `01_commits.json`.

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
- Outputs `03_product_map.json`.

### Stage 04 — prefilter_commits
- Loads compiled rules and applies the multi-level filter hierarchy.
- Kept commits → `04_filtered_commits.json` (input for scoring).
- Dropped commits → same file with `_filter_reason`.
- Also writes `output/filtered_commits.*` (JSON, CSV, HTML, XLSX, ODS).

### Stage 05 — score_commits
- Reads `04_filtered_commits.json`.
- Evaluates all rules of all active profiles for each commit.
- Supports parallel scoring via multiprocessing (`collect.score_workers`).
- Outputs `05_scored_commits.json` with `score`, `matched_profiles`,
  `product_evidence`, and `scoring.profiles` per commit.

### Stage 06 — postfilter_commits
- Sorts scored commits descending by score.
- Drops commits below `filter.min_score`.
- Dropped commits get `_filter_reason: score_below_threshold` and are
  appended to `04_filtered_commits.json`.
- Assigns `_rank` (1-based) to kept commits.
- Outputs `06_relevant_commits.json`.

### Stage 07 — report_commits
- Generates all outputs under `<work_dir>/output/`:
  - `relevant_commits.json` / `.csv` / `.xlsx` / `.ods`
  - `summary.html` — interactive report with sortable/filterable table,
    column-visibility toggle, CSV export, URL-hash filter state, dark mode
  - `profile_summary.json` and `profile_matrix.json` / `.csv`
  - `report_stats.json`

## compiled_rules.json schema

```json
{
  "rules": {
    "rule_set_x": {
      "keywords_whitelist": ["…"],
      "path_whitelist":     ["…"],
      "…": []
    }
  },
  "profiles": {
    "my_profile": {
      "rules":  { "rule_set_x": { "weight": 80 } },
      "merged": { "keywords_whitelist": ["…"], "…": [] }
    }
  }
}
```

Rule pattern bodies are stored once; each profile entry contains only weights
and the merged union of all its rules' patterns.

## State tracking

Each stage writes status, timing, and key counters to
`<work_dir>/pipeline_state.json`. The `--resume` flag skips stages that are
already recorded as done. `--from N` calls `wipe_downstream()` to clear
stale cache files before re-running.

## Library modules

| Module | Role |
|---|---|
| `lib/config.py` | Comment-aware JSON loader, `${VAR}` expansion, path resolution |
| `lib/profile_rules.py` | Compile and load profile/rule sets |
| `lib/scoring.py` | Per-commit scoring, metadata extraction |
| `lib/patterns.py` | Pattern compilation, matching, `precompile_rules()` |
| `lib/pipeline_runtime.py` | Stage state, progress tracking, `wipe_downstream()` |
| `lib/html_report.py` | HTML summary generation |
| `lib/spreadsheet.py` | XLSX (openpyxl) and ODS export |
| `lib/gitutils.py` | `git log` parsing |
| `lib/history_map.py` | Historical Makefile walking |
| `lib/kbuild.py` | Kbuild static map |
| `lib/parse_kconfig.py` | `.config` parsing |
| `lib/validation.py` | Config validation |
| `lib/manifest.py` | Version and manifest loading |
| `lib/logsetup.py` | Logging configuration |
| `lib/stages/` | Stage business logic (one module per stage) |
