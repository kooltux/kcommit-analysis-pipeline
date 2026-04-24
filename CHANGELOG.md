## v8.3 (2026-04-24)

### New Features
- **REQ-2** JSON config files now support shell-style inline `#` comments using
  regex `(^|\s+)#.*$` in `_strip_json_comments()`: a `#` at column 0 or
  preceded by whitespace strips the rest of that line.  A `#` immediately
  following a non-space character (e.g. `"#FF0000"`, `"http://x.com/p#frag"`)
  is NOT treated as a comment — making the rule safe for all JSON string values.
  Line-number preservation (blank/space replacement) is maintained.
- **REQ-3** Pattern `.txt` rule files now support the same bash-style inline `#`
  comment convention in `_read_patterns()`.  Text after whitespace + `#` is
  stripped; a `#` not preceded by whitespace (e.g. `re:foo#bar`) is kept.
  Whole-line `#` comments continue to work as before.
- **REQ-4** All 66 `.txt` rule files now open with an exactly 5-line syntax
  guide documenting the three pattern forms (keyword, glob, `re:REGEX`) and the
  inline comment convention, replacing the old single-line comment notice.

### Cleanup
- **REQ-1** `configs/example-arm-embedded-default.json` deleted.  The fully
  annotated `configs/example-arm-embedded-full.json` is the single reference
  example; the default config was a strict subset with fewer comments and less
  documentation value.

## v8.2 (2026-04-24)

### Bug Fixes
- **#1** HTML report footer now uses `VERSION` from `lib.manifest` instead of
  the hardcoded string `"v7.18"`.
- **#2** `html_report.generate_html_report()` now reads `output/relevant_commits.json`
  (the correct stage-06 output). The previous path `output/scored_commits.json`
  does not exist, causing the report table to always be empty.
- **#5** `output/summary.html` added to `STAGE_OUTPUTS['report_commits']` so a
  forced `--from 6` or `--force` run correctly wipes the stale HTML file.

### Architecture
- **#3** `html_report._load_json()` removed; all JSON loading now goes through
  `config.load_json()` — single implementation, single error handling path.
- **#6** Legacy alias block in `config.py` removed (`cfg['inputs']['profiles_dir']`,
  `cfg['profiles']['dir']`, etc.). All callers use `cfg['paths']` directly.
- **#7** `pipeline_state` key removed from `report_stats.json`. Consumers that
  need stage timing data should read `pipeline_state.json` directly.
- **#8** `profile_rules._load_json_with_comments()` removed; the module now uses
  `config._load_json()`, which benefits from the improved comment-stripping below.
- **#9** `start_stage()` and `update_stage_progress()` display indices are now
  derived from `MANIFEST.json` pipeline_stages entries (0-based), eliminating
  seven hardcoded magic-number pairs across the stage scripts.
- **#11** `inputs.kernel_config` and `inputs.build_dir` migrated to the `kernel`
  config section. Stage 02, `validation.py`, `_dry_run`, and both example configs
  updated accordingly.
- **JSON** `_strip_json_comments()` now replaces comment content with blank lines
  and spaces instead of removing lines outright. `json.JSONDecodeError` line
  numbers now refer to the original source file, making config errors easy to
  locate.

### Performance
- **#15** `_PRECOMPILED_IDS` in `scoring.py` converted from a plain `set` to a
  `weakref.WeakSet`, preventing memory leaks in long-running processes and test
  suites where `profile_rules` dicts are rebuilt repeatedly.

### Cleanup
- **#4** `lib/rules.py` deleted — never imported by anything since v7.17.
- **#10** `validate_config_only()` docstring corrected from `"v9.0 changes"` to
  `"v8.1 changes"`.
- **#12** `html_report.py` fully converted from `%`-style string formatting to
  f-strings, consistent with the rest of the codebase.
- **#13** `tools/generate_message_whitelist.py` listed in `MANIFEST.json` under
  a new `"tools"` key, and noted in `README.md`.
- **#14** `html_report.py` module docstring updated to document v8.1 and v8.2
  changes (was still showing `v7.18 changes vs v7.17`).

## v8.1 (2026-04-24)

### Fixes
- **#3** `score_commit()` blacklist now scoped per-profile: a commit blacklisted
  in profile A is no longer silently discarded from profile B.
- **#4** Parallel scoring fallback in stage 05 now prints a WARNING instead of
  silently downgrading to serial mode.
- **#5** `subprocess.call` replaced with `subprocess.run` in `lib/validation.py`.

### Performance
- **#6** `_load_hints()` in `scoring.py` now uses `functools.lru_cache`; hints
  JSON is read from disk once per process instead of once per commit.
- **#8** `validate_config_only()` added to `lib/validation.py`; stages 01-06 now
  call this lighter variant (no git subprocess), eliminating 12 redundant git
  subprocesses per full pipeline run. Stage 00 and dry-run keep full validation.
- **#15** `precompile_rules()` is now idempotent via `_PRECOMPILED_IDS` guard.

### Correctness
- **#2** `profile_matrix.csv` added to `STAGE_OUTPUTS['report_commits']` so it
  is correctly wiped on `--from 6` / `--force`.
- **#13** `kbuild_static_map.json` added to `STAGE_OUTPUTS['collect_build_context']`.
- **#14** History map failure threshold configurable via
  `history_mapping.max_failure_rate` (default 0.05).

### Architecture
- **#1** All stage scripts and orchestrator now use `cfg['paths']['work_dir']`
  instead of re-deriving the work directory from `cfg['project']['work_dir']`.
- **#9** `STAGES` list in `kcommit_pipeline.py` derived from `load_manifest()`
  — `MANIFEST.json` is now the single source of truth for stage ordering.
- **#11** `concurrent.futures` import moved to module top-level in `history_map.py`.
- **#12** `_dry_run()` uses `cfg['paths']['work_dir']`.

### Cleanup
- **#7** Dead import `get_pipeline_state` removed from `kcommit_pipeline.py`.
- **#10** Remaining `%`-format strings in `00_prepare_pipeline.py` replaced with f-strings.
- **#16** `extract_patch_features()` dead alias deleted from `lib/scoring.py`.
- **#17** `_active_profiles()` renamed to public `active_profile_names()`.

## v8.0 (2026-04-24)

### Breaking changes
- Python 2 compatibility shims removed everywhere (`from __future__ import
  print_function`, `import io`, `io.open()`). Minimum Python is 3.6+.
- `lib/io_utils.py` deleted; `load_json`/`save_json` moved to `lib/config.py`;
  `ensure_dir` replaced with `os.makedirs(..., exist_ok=True)` inline.
- `lib/parse_dts.py` and `lib/parse_logs.py` deleted (unused dead code).
- `cfg['paths']` canonical namespace added; legacy `cfg['inputs']`,
  `cfg['profiles']['dir']`, etc. kept as aliases but deprecated.
- `--stage` and `--from` are now mutually exclusive; passing both is an error.

### New features
- `lib/manifest.py`: single source of truth for VERSION; version string in
  kcommit_pipeline.py dry-run and argparse reads MANIFEST.json at runtime.
- `lib/validation.py`: git-ref validation (rev_old/rev_new verified via
  `git rev-parse --verify`), scoring multiplier range checks, profile weight
  0-100 enforcement, score_workers integer/non-negative check.
- `lib/scoring.py`: `precompile_rules()` compiles all pattern strings to
  re.Pattern once per worker process, avoiding per-commit recompilation at scale.
- `06_report_commits.py`: `avg_score` (total_score/count) added to each profile
  entry in profile_summary.json; HTML report shows Avg score column.
- `lib/history_map.py`: git-show failures now counted; >5% failure rate raises
  RuntimeError to fail the stage loudly; <5% prints a stderr warning.
- `wipe_downstream()`: accepts explicit `stage_order` list for deterministic
  ordering on fresh workspaces (no longer depends on stored index fields).
- `subprocess.call` replaced with `subprocess.run` in orchestrator.
