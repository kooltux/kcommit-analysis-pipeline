# Pipeline Internals

## Stage details

### Stage 00 — prepare_pipeline
- Validates configuration and all referenced paths.
- Loads all active profile JSON files and resolves rule directories.
- Compiles rule patterns into `compiled_rules.json` (deduplicated: each
  rule body stored once, referenced by name from each profile).
- Writes `prepare_summary.json` with active profile names and rule counts.

### Stage 01 — collect_commits
- Runs `git log <rev_old>..<rev_new> --name-only` (optionally `--numstat`,
  `--no-merges`, `--first-parent`).
- Parses commit metadata: SHA, subject, body, author, timestamps, touched files.
- Outputs `commits.json`.

### Stage 02 — collect_build_context
- Reads the kernel `.config` to extract enabled `CONFIG_*` symbols.
- Scans `build_dir` for compiled `.o`/`.ko` artifacts.
- Parses `kernel_build_log` and `yocto_build_log` for compiled object names.
- Parses DTS roots for device-tree source paths.
- Outputs `build_context.json` and `kbuild_map.json`.

### Stage 03 — build_product_map
- Combines `build_context.json` with the static Kbuild map.
- Optionally walks historical Makefiles via `lib/history_map.py` to extend
  the `CONFIG_* → source file` mapping across the revision range.
- Outputs `product_map.json`.

### Stage 04 — prefilter_commits
- Loads compiled rules and applies the multi-level filter hierarchy.
- Kept commits → `filtered_commits.json` (input for scoring).
- Dropped commits → same file with `_filter_reason`.
- Also writes `output/filtered_commits.{json,csv,html,xlsx,ods}` for each
  format enabled in `reports.outputs`.

### Stage 05 — score_commits
- Reads `filtered_commits.json`.
- Evaluates all rules of all active profiles for each commit.
- Supports parallel scoring via multiprocessing (`collect.score_workers`).
- Outputs `scored_commits.json` with `score`, `matched_profiles`,
  `product_evidence`, and `scoring.profiles` per commit.

### Stage 06 — postfilter_commits
- Sorts scored commits descending by score.
- Drops commits below `filter.min_score`.
- Dropped commits get `_filter_reason: score_below_threshold` and are
  appended to `filtered_commits.json`.
- Assigns `_rank` (1-based) to kept commits.
- Outputs `relevant_commits.json`.

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


- v10.2.0: HTML commit details now expose a rule-by-rule scoring trace, including matched patterns/paths/SHA values, per-rule score, per-profile score, and final combined score.

- v10.2.0: Non-HTML outputs now expose rule-analysis details too: JSON includes rule_trace.json and summary XLSX/ODS include a Rule Trace sheet.

- v10.2.0: HTML reports now support sidecar table datasets (`relevant_commits.table.json`, `filtered_commits.table.json`), sharded per-commit detail JSON under `output/commits/aa/bb/<sha>.json`, optional compressed embedded commit maps, and canonical git-log-style field ordering for commit detail payloads.

## Miniature test fixture

A test-only miniature pipeline fixture lives under `tests/`. It includes a tiny kernel-like tree in `tests/mini-sample/mini-kernel`, dedicated test profiles/rules in `tests/mini-sample/`, and a sample config at `tests/mini-sample/configs/test-mini.json`. The regression test `tests/test_full_pipeline_with_mini_inputs.py` uses these assets to exercise stage preparation, build-context capture, and command/report flow without depending on external repositories.


## v11.4.0 report changes

- Stage 07 now emits incremental progress information while generating HTML sidecar assets and final pages.
- HTML reports now load evaluation metadata from `report_metadata.json`, and the left pane shows repository revisions and analysis options.
- Main HTML report tables no longer show the `product evidence` column; commit detail views keep the information under the shorter `Evidence` label.
- HTML output is further externalized into `relevant_commits.table.json`, `filtered_commits.table.json`, `report_metadata.json`, and sharded `commits/<sha>.json` detail files.


## v11.3.2 changes

- Stage 07 emits incremental progress while generating report metadata, sidecar indexes, detail JSON, and HTML pages.
- HTML reports load evaluation metadata from `report_metadata.json`.
- Main HTML tables hide `Product Evidence`; commit detail views show the shorter `Evidence` label.
- Current validated baseline: 465 tests passing, 85% `lib/` coverage.
