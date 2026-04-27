## v8.4

### Critical Bug Fixes
- **`02_collect_build_context.py`**: fixed a latent `NameError` — `inputs` was
  referenced but never defined in the function body. `kernel_build_log`,
  `yocto_build_log`, and `dts_roots` now correctly read from `cfg['kernel']`.
- **`lib/scoring.py`**: `commit_blacklist` entries now populate
  `_profile_blacklisted` in the first-pass loop, preventing blacklisted SHAs
  from appearing in `matched_profiles`.
- **`lib/scoring.py`**: `_load_hints_from_path()` uses the comment-aware JSON
  loader — a `//` or `#` comment in `subsystem_path_hints.json` no longer
  silently discards the entire hints dict.

### JSON Comment Parsing (`lib/config.py`)
- `INLINE_COMMENT_RE` exported as a public name; `lib/profile_rules.py` now
  imports it instead of re-defining the identical compiled regex.
- New `_INLINE_SLASH_RE` strips inline `//` comments when `//` is preceded by
  whitespace — safe for `://` in URLs (`"http://x.com"` unchanged).
- `_strip_json_comments()` replaces all comment characters with **spaces**
  (not empty strings), preserving both line numbers and column positions so
  `json.JSONDecodeError` reports the exact location in the original source file.

### Scoring (`lib/scoring.py`)
- `symbol_match` added to `_DEFAULT_WEIGHTS` (default `1.0`) and applied as a
  multiplier to `config_map` and `config_text` product-evidence components.
  The `"symbol_match": 1.2` in the example config now has effect.
- `_profile_multipliers()` handles list form of `profiles.active` — all listed
  profiles receive multiplier `1.0` instead of silently producing empty results.

### Validation (`lib/validation.py`)
- `history_mapping.mode` validated against allowed values
  (`range`/`sampled`/`full`/`disabled`).
- `history_mapping.sample_step` validated as a positive integer.

### Profile Rules (`lib/profile_rules.py`)
- `_read_patterns()` emits `warnings.warn` for missing pattern files so that
  a typo in a profile rule path is immediately visible rather than producing
  silent zero-coverage scoring.

### Reports
- `06_report_commits.py`: `profile_matrix.csv` header changed to
  `commit, subject, profile, total_score, profile_score`; the new
  `profile_score` column contains the per-profile contribution.
- `kcommit_pipeline.py`: `output/profile_summary.json` added to
  `STAGE_OUTPUTS['report_commits']` so `--from 6` correctly wipes it.

### Config Schema
- `configs/example-arm-embedded-full.json`: `kernel_build_log`,
  `yocto_build_log`, and `dts_roots` moved from the defunct `inputs` section
  into `kernel`. The entire `inputs` block is removed.
- Example config now documents `collect.jsonl`, `collect.include_parents`,
  and `history_mapping.max_failure_rate`.

### Code Hygiene
- `01_collect_commits.py`: last two `%`-format strings replaced with f-strings.
- `lib/html_report.py`: docstring updated to reflect v8.2–v8.4 history.

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
