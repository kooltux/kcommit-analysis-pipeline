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

## v7.18

### Performance
- `lib/parse_kconfig.py`: new `scan_kbuild_tree()` performs a single `os.walk`
  of the kernel source tree and returns both `(config_to_paths, kbuild_files)`.
  Stages 02 and 03 previously each ran a full independent traversal (~75k files,
  ~5k directories for a mainline kernel).  The result is computed once in stage
  02 and cached to `cache/kbuild_static_map.json` for stage 03 to reuse without
  any additional tree traversal.  Both old functions (`scan_makefile_config_map`,
  `scan_kbuild_makefiles`) are kept as thin backward-compat wrappers.
- `lib/kbuild.py`: `scan_kbuild_makefiles()` now delegates to
  `scan_kbuild_tree()` instead of performing its own independent `os.walk`.
- `lib/history_map.py`: parallel `git show` calls via
  `concurrent.futures.ThreadPoolExecutor` (default 8 workers, configurable via
  `collect.history_workers`).  Serial fallback preserved for single-core
  environments or when the executor is unavailable.  `progress_callback(done,
  total)` parameter added so stage 03 can display live progress.  Expected
  wall-clock speedup: 5–10x on a typical SSD + 4-core machine.
- `05_score_commits.py`: pool **initializer pattern** — `_worker_init()` stores
  `product_map`, `profile_rules`, and `cfg` as module-level globals in each
  worker process so they are pickled once at startup rather than once per commit
  task.  Uses `pool.imap()` for ordered streaming progress updates.

### Usability
- `lib/pipeline_runtime.py`: new `update_stage_progress(index, total,
  inner_fraction, label, n_done, n_total)` renders an in-place `\r` progress
  bar for within-stage loops so the terminal shows continuous feedback.
- `01_collect_commits.py`: `parents` field is opt-in via
  `collect.include_parents` (default `false`), significantly reducing
  `commits.json` size for large ranges (200k+ commits).
- `02_collect_build_context.py`: five progress milestones reported during
  kernel-config loading, log reading, build-dir scan, and Kbuild tree walk.
- `03_build_product_map.py`: live progress from parallel history-map git-show
  calls fed through `progress_callback`.
- `04_enrich_commits.py`: within-stage progress updated ~50 times.
- `05_score_commits.py`: within-stage progress updated ~80 times.
- `06_report_commits.py`: `profile_summary.json` now stores
  `{profile: {count, total_score}}` instead of a bare integer; HTML report
  renders this as a proper summary table.

### Correctness
- `lib/config.py`: `_strip_json_comments()` already joined lines with `\n`
  (correct since v7.17).  No change needed.
- `06_report_commits.py`: `profile_summary` dict now carries `total_score` in
  addition to `count`, giving the HTML report richer per-profile statistics.

### Python 3.6 compatibility
- No f-strings, no walrus operator, no APIs introduced after Python 3.4.
- `concurrent.futures.ThreadPoolExecutor`: available since Python 3.2.
- `multiprocessing.Pool` with `initializer`: available since Python 3.3.
- `os.makedirs(exist_ok=True)`: available since Python 3.4.1.
- All new code uses `from __future__ import print_function` and `io.open()`.

# Changelog

## v7.17 (2026-04-23)

### New features

- **`--dry-run` flag** in `kcommit_pipeline.py`: loads config, prints all
  resolved paths (TOOLDIR, work_dir, source_dir, revision range, profiles,
  scoring weights), validates inputs, and exits without running any stage.

- **`--from STAGE` flag** in `kcommit_pipeline.py`: run from the named or
  numbered stage onwards; wipes intermediate output files for all downstream
  stages and resets their status in `pipeline_state.json`.

- **`--force` flag** in `kcommit_pipeline.py`: re-run a stage even if it is
  already recorded as `ok`; implies downstream wipe.

- **`fail_stage()`** in `lib/pipeline_runtime.py`: marks a stage as `failed`
  in `pipeline_state.json`, records `duration_sec` and an `error` message.
  All six stage scripts now call `fail_stage` in their `except` blocks.

- **`get_pipeline_state()`, `is_stage_done()`, `wipe_downstream()`,
  `init_pipeline_state()`** added to `lib/pipeline_runtime.py`.  State dict
  is now keyed by stage name (string) instead of a positional list, so
  individual-stage re-runs never create duplicate entries.

- **`lib/scoring.extract_stable_hints(commit)`**: replaces the old
  `extract_patch_features(subject)`.  Reads the full commit dict (subject +
  body) to detect `Fixes:` trailers, `Cc: stable@` lines, CVE references, and
  syzbot mentions.  Old name kept as a backward-compatibility alias.

- **Triple-threat stable bonus**: when a commit has both a `CVE-` reference,
  a `Fixes:` trailer, *and* `Cc: stable@`, `stable_score` gets an extra +30 pts.

- **`lib/scoring.infer_touched_paths(subject, cfg=None)`**: new `cfg` parameter
  loads keyword→path mappings from
  `configs/scoring/subsystem_path_hints.json` (resolved via TOOLDIR) instead
  of an inline hardcoded table.  Falls back to an empty result when the file
  cannot be loaded.

- **`configs/scoring/subsystem_path_hints.json`**: 80+ keyword→path prefix
  mappings for common kernel subsystems (networking, security, mm, sched,
  drivers, filesystems, arch, …).

- **Real file ∩ config_to_paths matching** in `score_commit`: actual changed
  files from `commit['files']` are now intersected with the Kbuild-derived
  `config_to_paths` map to produce strong `config_map:CONFIG_FOO` evidence
  tags, giving a +20 pts product score per matched config symbol.

- **Message blacklist pre-filter** in `score_commit`: commits matching any
  `keywords_blacklist` pattern are returned with `score=0` immediately,
  skipping all expensive product/Kbuild/profile scoring.

- **Profile weight multipliers**: `profiles.active` in the config now accepts a
  dict form `{"profile_name": weight_0_100, …}`.  Weights are divided by 100 to
  produce a float multiplier applied to each profile's per-rule score total.
  The old list form is still accepted for backward compatibility.

- **`scoring` section in config**: `cfg['scoring']` accepts float multipliers
  for the four sub-scores (`product`, `security`, `performance`, `stable`).
  Defaults: 1.0 / 1.5 / 1.0 / 1.2.

- **`collect` section additions**:
  - `max_commits` (int, default 0 = no limit): safety valve that stops
    collection after N commits and prints a warning.
  - `score_workers` (int, default 0 = auto = min(4, cpu_count)): controls
    multiprocessing pool size in stage 05.
  - `jsonl` (bool, default false): if true, stage 01 also writes
    `cache/commits.jsonl` (newline-delimited JSON).

- **`profile_coverage` metrics** in `report_stats.json` (stage 06):
  - `commits_matched_zero_profiles`
  - `commits_matched_one_profile`
  - `commits_matched_multiple_profiles`
  These also appear in the HTML report as a **Profile Coverage** block.

- **HTML report** (`lib/html_report.py`): table now shows `score` (single
  combined integer), plus `security`, `performance`, `product`, `stable`
  columns from the `scoring` sub-dict; old `candidate_score` column removed.
  Profile Coverage card block added.  `top_n` and `report_title` configurable
  via `templates` config section.

- **`kernel_config` and `build_dir` are now optional** (`lib/validation.py`):
  missing or non-existent values produce a printed notice and allow the pipeline
  to continue; they are no longer blocking errors.

- **`MANIFEST.json`** version bumped to `v7.17`; `scoring_dir` field added;
  `example-workspace-template.json` removed.

### Breaking changes

- `pipeline_state.json` state structure changed from a list to a dict keyed by
  stage name.  Old state files should be deleted before running v7.17.

- `score_commit` output: `candidate_score` / `security_score` /
  `performance_score` / `stable_score` top-level keys replaced by `score` (int)
  and `scoring` sub-dict.  CSV reports updated accordingly.  Any custom
  downstream consumers of `scored_commits.json` must be updated.

- `extract_patch_features(subject)` is retained as an alias but the primary
  function is now `extract_stable_hints(commit)`.

### Fixes

- `lib/config._strip_json_comments` now rejoins cleaned lines with `'\n'`
  instead of `' '`, preserving multi-line structure and avoiding edge-case
  JSON parse failures on configs with many comment lines.
