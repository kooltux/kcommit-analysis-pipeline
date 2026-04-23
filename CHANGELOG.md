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
