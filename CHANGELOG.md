# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Changed

- AI server defaults to `127.0.0.1:8000`. Explicit `-l PATH`/`--log-file PATH`
  is mandatory in daemon mode, with no default log-file path.
- Foreground mode logs only to stderr when no file is selected. An explicit
  file is the sole log destination in either mode; startup fails if unwritable.
- Updated logging-mode regression tests and startup documentation.
- Added stdout startup summaries with the connection URL and request-completion
  logs with duration and safe failure reasons, including malformed requests,
  timeouts, disconnects, and internal errors. Added corresponding regression tests.

## v19.12.0 — feat: configurable AI server front page and operation (2026-10-08)

### Added

- Configurable external AI server front page via `ai.front_page_path` in
  `configs/conf.d/07_ai.json`, packaged by Stage 08 and served as UTF-8 Markdown
  at `/` and `/README.md` under the existing authentication and access logging.
- Front-page preparation, packaging, HTTP, and smoke-test coverage.
- Shared guide organized for human readers, AI clients, and automation/testing,
  including curl/shell and read-only Python examples with chapter-order tests.

### Changed

- Generated `serve_ai.pyz` starts in the background on `0.0.0.0:8000` by default;
  `-d`, `--debug`, and `--no-daemon` are aliases for foreground operation.
- Access logs append to `/var/log/kcommit-analyze-ai-server.log`, configurable
  with `--log-file`; each response emits one compact line, including errors.
- Optional `--auth USER:PASSWORD` gates all endpoints with HTTP Basic authentication.
  Plain HTTP remains unencrypted; omitting authentication produces a warning.
- Startup checks log access and socket binding before detachment, reports the
  daemon PID, and supports clean signal shutdown. The AI smoke-test runner uses
  explicit foreground operation and a temporary access log.
- Added server regression coverage and updated usage/security documentation.

### Compatibility

- Default listener and process behavior have changed. Explicit positional port
  and host remain supported; regenerate existing zipapps to receive updates.
- Minor release requested by the user; existing defaults changed as described above.

## v19.11.1 — fix: configuration and Stage 07 consistency (2026-10-07)

### Fixed

- `--override` recursively merges objects while replacing all lists, restoring the documented override semantics.
- Referenced, empty built-in variables (`WORKSPACE`, `TOOLDIR`, `CONFIGDIR`, `CWD`) now cause a clear configuration error instead of silently producing paths such as `/work`. Variables not referenced by the configuration remain optional.
- Removed the trailing comma in `configs/conf.d/02_profiles.json` that prevented the shipped example configuration from loading.
- Stage 07 records all successfully written spreadsheets in `report_stats.generated_files`, including ODS and profile-summary/profile-matrix outputs.
- Restored the Stage 07 module docstring and replaced the hardcoded progress total with the manifest-derived `NSTAGES` in terminal progress and `runtime_status.json`.

### Tests

- Added regression coverage for override semantics, built-in variable requirements, shipped configuration parsing, spreadsheet output tracking, and stage module docstrings; updated the Stage 07 progress assertion.
- User reported that all tests passed before release preparation. Final release-tree QA remains required.

### Compatibility

- Override lists replace instead of accumulating; callers relying on the accidental list-union behavior must supply the complete desired list.
- No cache or on-disk format changes.

---

## v19.11.0 — refactor: remove product-specific rule-name alias (2026-10-01)

### Removed

- **lib/profile_rules.py** — `_rule_name_candidates()` and its call sites in `compile_rules_for_config()` and `load_profile_rules()`. Rule names are now looked up exactly as written in the profile, first in the configured `rules_dirs`, then in the built-in `configs/rules/` tree. The hardcoded legacy-prefix fallback to an unprefixed built-in rule no longer exists.

### Changed

- **docs/PROFILES_AND_RULES.md**, **docs/CONFIGURATION.md** — the legacy rule-name fallback sentences are removed; both documents now state that rule names are resolved exactly as written, and `docs/CONFIGURATION.md` notes that several `rules_dirs` entries may be listed (names must be unique across them).
- **configs/conf.d/02_profiles.json** — the commented multi-directory `rules_dirs` example uses a neutral directory name.
- **CHANGELOG.md** — restored the v19.6.0, v19.5.0 and v19.4.2 entries that had been truncated away in earlier commits (recovered from the `v19.5.0` and `v19.6.0` tags).

### Added

- **tests/test_profile_rules.py** — tests for exact rule-name resolution from an external directory, for the absence of any prefix-based fallback (an unknown prefixed name raises `RuntimeError`), and for lookup across several `rules_dirs` entries. Product-specific names are removed from the test data.

### Compatibility

- External configurations that referenced rule names relying on the removed prefix fallback must rename those rules (or provide the matching rule folders); they now fail with the usual "rule folder ... not found" error.
- No other configuration, cache or on-disk format changes.

### Tests

- Full test suite passed before release preparation.

---

## v19.10.0 — feat: optional advisory AI analysis (2026-09-29)

### Added

- Opt-in Stage 08 packages prefilter-kept commits into checksummed chunks with schemas, a prompt, and a portable result server.
- `ai-import` validates returned results and adds advisory assessments to report copies without changing scores, rankings, or cherry-pick results.
- README and `docs/AI_ANALYSIS.md` document the workflow; new tests cover the contract, stage dispatch, import invariants, and reports.

### Compatibility

- Ordinary runs still stop at Stage 07; AI preparation requires `--ai` or an explicit Stage 08 run.

### Tests

- 971 tests passed before the version and changelog edits; rerun required on the final tree.

---

## v19.9.1 — fix: progress-bar visibility and consistency across all stages (2026-09-11)

### Fixed

- **Stage 01 hunk counting** — `batch_count_hunks()` is now called with a real `progress_callback`, replacing two static `print()` lines that bracketed the call with total silence for however long the underlying `git show` batches took (minutes on large commit ranges — confirmed on a 183,716-commit real-world run). The total (`len(shas)`) is known before the call starts, so a determinate bar is shown throughout, not a spinner.
- **Cherry-pick progress bar unified** — `batch_can_cherry_pick_cached()` (`lib/gitutils.py`) now renders progress through the shared `lib.pipeline_runtime.update_stage_progress()` bar instead of a standalone block-character (`█`/`░`) bar written directly to stdout. `lib/stages/st05_score.py`'s `_enrich_cherry_pick()` passes `stage_index=5, stage_total=NSTAGES` so the cherry-pick bar now looks identical to every other stage's bar instead of a visually distinct style. The now-unused `_progress_bar()`/`_format_eta()` helpers in `lib/gitutils.py` are removed.
- **Progress bar width standardized** — `update_stage_progress()`'s bar is now a fixed 25 characters, each representing exactly 4% of progress (previously 16 characters at ~6.25%/char). `finish_stage()`'s `_bar()` helper uses the same 25-character width, so every rendered bar across the pipeline — outer stage bars, inner sub-stage bars, hunk counting, cherry-pick testing — now uses one consistent visual scale.

### Added

- **Indeterminate/spinner progress mode** — `update_stage_progress()` now supports three display modes instead of the original always-a-bar behavior:
  1. **No count at all** (`n_done` is `None`) — e.g. `st02_build_context.py`'s and `st03_product_map.py`'s hand-computed milestone fractions (0.10, 0.25, ..., 0.90), which never track a raw item count. Renders the fixed 25-character bar directly from the caller's fraction.
  2. **A count but no total** (`n_done` given, `n_total` is `None`) — e.g. `st01_collect.py`'s unbounded `git log` collection loop, where the total commit count is genuinely unknowable until the loop finishes. Renders a rotating spinner with elapsed time and the raw count, instead of a frozen, misleading `0/0` bar that looked hung.
  3. **Both count and total known** — the full determinate bar with counts, rate, and ETA (unchanged from prior versions).

  This three-way rule was corrected after live testing surfaced a regression in an earlier draft of this fix: an initial "spinner whenever `n_total` is missing" rule incorrectly downgraded stage 02/03's milestone bars to spinners, since those calls never pass `n_done`/`n_total` at all. No caller-side changes were needed in any stage to support the corrected rule.
- **Test coverage**: `tests/test_pipeline_runtime_extra.py` gains 10 new tests for the fixed bar width and all three display modes (milestone-fraction bar, count-without-total spinner, full determinate bar, and the transitions between them). `tests/test_gitutils_cherry_progress.py` (new file) covers the unified cherry-pick progress rendering, caller-supplied `progress_callback` forwarding, and cached-result reuse. `tests/test_st01_collect_run.py` gains 4 new tests for the hunk-counting progress callback wiring.

### Compatibility

- No breaking API changes. `batch_can_cherry_pick_cached()` gains optional `stage_index`/`stage_total`/`label` keyword arguments (all default to disabling shared-renderer output, preserving prior behavior for any caller that omits them).
- Visual output only: no config, cache, or on-disk format changes.

### Tests

- Full test suite passed before release preparation.

---

## v19.9.0 — feat: direct per-revision cherry-pick cache files (2026-09-10)

### Changed

- **Cherry-pick cache layout** — the SQLite cache for `collect.cherry_pick_test` now stores one direct file per target revision (`<cherry_pick_cache_dir>/<safe-rev_old>`, e.g. `<dir>/v6.1.1`) instead of a per-revision subdirectory containing a generic `cherry.db` file (previously `<dir>/<rev_old>/cherry.db`). Revision names are filesystem-normalized: `/` and `\` are both replaced with `_`, so refs like `origin/stable/linux-6.1.y` map to a single safe filename instead of creating nested directories.
- **lib/cherrypick_paths.py** (new) — path/cache-layout helpers extracted from `lib/cherrypick_db.py`: `_safe_revision_filename()`, `get_cherry_db_path()`, `ensure_cache_dir()`, `load_or_create_db()`, `delete_db()`. `ensure_cache_dir()` now only creates the shared `cache_dir` — no per-revision subdirectory is created.
- **lib/cherrypick_db.py** — re-exports all five path helpers from `lib.cherrypick_paths` for backward compatibility; existing `from lib.cherrypick_db import ...` call sites are unaffected.

### Added

- **tests/test_cherrypick_paths.py** — new test module covering direct-file path construction, `/` and `\` normalization, base-directory-only creation, and `delete_db()` against the new layout.
- **tests/test_cherrypick_db.py** — expanded with a backward-compatibility test verifying `lib.cherrypick_db` still exposes the path helpers after the split, plus additional CherryDB coverage (single-result round trip, empty-input short-circuit, `count()`/`get_all_shas()`).

### Compatibility

- Backward compatible at the Python API level: all five path helpers remain importable from `lib.cherrypick_db`.
- **Not** backward compatible on disk: existing `<cherry_pick_cache_dir>/<rev_old>/cherry.db` caches from prior versions are not read by v19.9.0. Cherry-pick results will be re-tested and written to the new direct-file location on first run after upgrading. This is expected — cached results are a pure performance optimization (10-100x speedup on reruns), not a correctness requirement.

### Tests

- Full test suite passed before release preparation.

---

## v19.8.1 — fix: support very large commit ranges in hunk and cherry-pick processing (2026-09-10)

### Fixed

- **Stage 01 hunk counting** — `batch_count_hunks()` now splits commit SHAs into bounded `git show` batches (default: 2,000 SHAs) instead of passing an entire range in one argv. This prevents `OSError: [Errno 7] Argument list too long` on large ranges.
- **Git output decoding** — `run_git()` now uses UTF-8 with replacement decoding for stdout and stderr. A malformed byte in historical commit metadata or patch content can no longer abort a large `git show` batch with `UnicodeDecodeError`.
- **Stage 05 cherry-pick cache lookup** — `CherryDB.get_results()` now splits SHA `IN (...)` lookups into internal chunks of 900 values, below SQLite’s traditional 999-variable ceiling. This prevents `too many SQL variables` when many commits are scored.

### Added

- **`collect.hunk_count_chunk_size`** — optional hunk-count batch-size tuning key; default `2000`. It is documented in `docs/CONFIGURATION.md` and normally should not need changing.
- **Regression coverage** — tests for hunk chunking, configured batch size, cross-chunk progress, stable SHA deduplication, and CherryDB cross-chunk result lookup/duplicate handling.

### Compatibility

- No breaking API or configuration changes.
- Existing configurations retain their behavior; large ranges now execute safely in bounded Git and SQLite batches.

### Tests

- Full test suite passed before release preparation.

---

## v19.8.0 — feat: portable helper scripts for output archives (2026-09-04)

### Added

- **configs/assets/json_query.sh** — Self-contained JSON query tool:
  - Query JSON files using dotted notation (e.g., `kernel.rev_old`)
  - Returns scalars as plain text, objects/arrays as compact JSON
  - Determines its own location — works when copied anywhere
  - Used by archive_output.sh and for manual queries

- **configs/assets/archive_output.sh** — Automated archive creation:
  - Extracts `kernel.rev_old` and `kernel.rev_new` from config
  - Creates timestamped archives: `kernel_commit_analysis_<old>_<new>_<YYYYMMDD>.tar.gz`
  - Self-contained — uses json_query.sh from same directory
  - Supports WORKSPACE env variable or script directory

- **lib/stages/st07_report.py** — `_copy_helper_scripts()` function:
  - Copies scripts to `output/scripts/` subdirectory at end of stage 07
  - Makes scripts executable (0o755)
  - Scripts are portable with the output directory

### Organization

Scripts are placed in `output/scripts/` subdirectory:
```
output/
  scripts/
    json_query.sh
    archive_output.sh
  pipeline_config.json
  summary.html
  ...
```

### Usage

```bash
# From output/ directory:
cd output/
./scripts/archive_output.sh              # Uses pipeline_config.json
./scripts/archive_output.sh config.json  # Or specify config

# Query config:
./scripts/json_query.sh pipeline_config.json kernel.rev_old
```

### Benefits

- **Portability** — output/ directory is self-contained with archive capability
- **Convenience** — One command to create properly-named archives
- **Flexibility** — json_query.sh reusable for any JSON queries

### Backward Compatibility

- No breaking changes
- Scripts are optional additions to output/
- Existing pipeline runs unaffected

---

## v19.7.0 — feat: pipeline_config.json manifest preserves non-expanded variables (2026-09-04)

### Added

- **lib/config.py** — New function `load_config_with_raw()` returns both expanded and raw (non-expanded) config versions:
  - `expanded`: Fully processed config with variable expansion and path resolution (existing behavior)
  - `raw`: Merged config with original variable references preserved (e.g., `${WORKSPACE}/work`)
  
- **lib/config.py** — New internal function `_build_raw_merged_config()` builds the raw merged config:
  - Includes are merged
  - `vars` section kept as-is (no expansion)
  - Paths not resolved to absolute paths
  - No `_meta` or `config_dir` added

- **tests/test_config_raw_manifest.py** — New test suite for raw config manifest generation:
  - `test_load_config_with_raw_returns_both_versions` — verifies both configs are returned
  - `test_raw_config_preserves_variables_with_includes` — tests includes with variables
  - `test_build_raw_merged_config_standalone` — tests the standalone function
  - `test_manifest_would_contain_variable_references` — documents expected manifest behavior
  - `test_raw_config_with_array_merges` — verifies array merges work in raw config

### Changed

- **lib/stages/st07_report.py** — `_dump_merged_config() now accepts `raw_cfg` parameter:
  - Uses raw (non-expanded) config for manifest generation
  - Preserves variable references like `${WORKSPACE}/work` in `output/pipeline_config.json`
  - Makes manifests more portable and reproducible across different environments
  
- **lib/stages/st07_report.py** — `run()` function updated to load raw config:
  - Calls `load_config_with_raw()` when config path is available
  - Falls back to expanded config if raw loading fails
  - Passes raw config to `_dump_merged_config()`

- **lib/stages/st07_report.py** — Module docstring updated to document v19.7.0 change

### Benefits

- **Portability** — Manifests can be reused across different environments without hardcoded absolute paths
- **Reproducibility** — Variable references show the intended configuration structure
- **Debugging** — Easier to understand config relationships when variables are visible

### Backward Compatibility

- Existing `load_config()` function unchanged — full backward compatibility
- Pipeline behavior unchanged — only manifest output format differs
- All existing configs work without modification

### Tests

New test file `tests/test_config_raw_manifest.py` with 6 test cases covering raw config generation.

---

## v19.6.1 — fix: filter internal metadata from pipeline_config.json manifest (2026-09-03)

### Fixed

- **lib/stages/st07_report.py** — `_dump_merged_config()` now filters out internal metadata before writing:
  - `_meta` section (internal diagnostics: config_path, config_dir, vars, include_events)
  - Standalone `config_dir` key (redundant; already in `paths` and `_meta`)
  - Only user-facing configuration keys are written to `output/pipeline_config.json`

### Changed

- **lib/stages/st07_report.py** — updated docstring to document the filtering behavior

### Tests

All 896 tests pass.

---

## v19.6.0 — feat: public configuration include mechanism with JSONC support (2026-09-03)

### Added

- **Configuration includes** — configs can now be split into ordered fragments using the top-level `include` key:
  - `"include": ["conf.d/base.json", "conf.d/extras.json"]`
  - Fragments may define their own `include` and `vars`
  - Paths resolved relative to the declaring fragment
  - `${CONFIGDIR}` supported in fragment-local vars and paths
  - Recursive includes allowed; cycles detected via active include chain
  - Shared fragments can be included through separate branches (no false-positive cycles)

- **Merge semantics**:
  - Objects: recursive union
  - Arrays: ordered union with stable canonical-JSON deduplication
  - Scalars/type conflicts: later source wins
  - Every scalar replacement and array contribution emits a warning and is recorded in `_meta.include_events`

- **Diagnostics** — composed config includes `_meta.include_events` with:
  - `scalar_replaced`: scalar overwritten
  - `array_contribution`: new elements added to array
  - Source path and old/new values for each event

- **JSONC support** — `//` line comments, `/* */` block comments, and `#` comments stripped before parsing

- **Example configuration** — `configs/example-arm-embedded-full.json` includes fragments in `configs/conf.d/`:
  - `00_vars_paths.json`, `01_kernel.json`, `02_profiles.json`, `03_filter.json`
  - `04_collect.json`, `05_history_mapping.json`, `06_reports.json`, `07_ai.json`

- **Merged output** — final composed config written to `output_dir/kcap-merged-config.json` for portability

- **Tests** — `tests/test_config_includes.py` covers:
  - Ordered includes and merge order
  - Array deduplication stability
  - Cycle detection
  - Shared fragments via separate branches
  - Fragment-local vars and CONFIGDIR resolution
  - Monolithic config compatibility

### Changed

- **lib/config.py** — `load_config()` now:
  - Accepts optional `include` key for ordered fragment composition
  - Validates unknown top-level keys only at root (fragments allow arbitrary keys)
  - Emits scalar replacement warnings during deep merge of nested objects
  - Populates `_meta.include_events` with merge diagnostics
  - Maintains backward compatibility with monolithic configs

- **lib/profile_rules.py** — uses public `load_json` instead of internal `_load_json`

- **docs/CONFIGURATION.md** — merged includes documentation section covering:
  - Overview and syntax
  - Merge semantics and examples
  - Cycle detection rules
  - Diagnostics format
  - Example configuration and test instructions

### Backward Compatibility

- Monolithic configs continue to work unchanged
- All existing config keys and behaviors preserved
- No breaking changes to API or config schema

### Tests

All 896 tests pass, including new include mechanism tests.

---

## v19.5.0 — feat: cherry-pick script as a configurable static asset + single JSON data file (2026-09-03)

### BREAKING

Cherry-pick execution now uses a single `cherry_pick.sh` script with a `--set`
argument, plus a `cherry_pick_data.json` data file, instead of separate
`cherry_pick_prefiltered.sh` and `cherry_pick_relevant.sh` scripts.

**Old workflow:**
```bash
./cherry_pick_relevant.sh    # apply relevant commits
./cherry_pick_prefiltered.sh # apply all prefilter commits
```

**New workflow:**
```bash
./cherry_pick.sh --set=relevant      # apply relevant commits
./cherry_pick.sh --set=prefiltered   # apply all prefilter commits
./cherry_pick.sh --help              # commit counts computed live from data file
```

### Added

- **configs/assets/cherry_pick.sh** — new static asset directory holding files
  that are copied verbatim into `output/` rather than generated. The
  cherry-pick script is the first resident: a fully generic, run-independent
  bash script with:
  - `usage()` function, automatically invoked on `-h`/`--help`, a missing or
    invalid `--set` value, and any unrecognized option -- no need to pass
    `-h` explicitly to see help on a usage error.
  - `getopt`-based option parsing for robust, standards-compliant argument
    handling (long options, `--`, combined short options, etc.).
  - Commit counts in the help text (`Total`, `Relevant`, `Prefiltered-only`)
    computed **live** from `cherry_pick_data.json` at run time -- never
    hardcoded, never stale.
  - Small Python snippets embedded via `python3 - <<'PYEOF' ... PYEOF`
    heredocs with a **quoted** delimiter, so bash performs no expansion or
    reinterpretation inside them; the data-file path and other values are
    passed as real `sys.argv` entries instead of being interpolated into the
    Python source text. This lets Python be embedded directly in the bash
    script (no companion helper file) while completely avoiding
    bash/Python nested-quoting corruption -- verified end-to-end with commit
    subjects containing parentheses and both quote styles.
  - `cp_one()` wrapper printing colorized per-commit progress and logging
    failures to `cherry_pick.log` (carried over from v19.4.2, now part of
    the static asset).
  - Branch-creation prompt (`cherrypicking_from_<rev_new>`) before starting.

- **`paths.assets_dir` config key** — new entry in the canonical `paths`
  namespace (alongside `work_dir`, `cache_dir`, `output_dir`), resolved with
  the same default/override convention already used by `reports.templates_dir`
  and `scoring.scoring_dir`: defaults to the pipeline's own
  `configs/assets/`, and accepts an absolute or `${CONFIGDIR}`-relative
  override in a product config (e.g. `"paths": {"assets_dir": "${CONFIGDIR}/assets"}`).
  Lets a product config ship its own customized `cherry_pick.sh` (e.g. with
  extra pre/post hooks) without forking the pipeline.

- **Testing section in README.md** — documentation on running the test suite:
  - Using the `run_tests` script (recommended)
  - Manual pytest invocation with `WORKSPACE` variable
  - Test structure overview with file-to-coverage mapping
  - Test fixtures and continuous integration notes

### Changed

- **lib/config.py** — added `assets_dir` to `CONFIG_SCHEMA['paths']` and to
  the canonical `paths` namespace populated by `load_config()`; resolution
  mirrors `templates_dir` exactly (default from the tool's own `configs/`
  tree, override read from the already-path-resolved `paths` dict, relative
  values re-resolved against `config_dir` defensively).

- **lib/cherrypick_script_gen.py** — complete rewrite to v19.5.0 design:
  - `write_cherry_pick_files()` now **copies** `cherry_pick.sh` byte-for-byte
    from `cfg['paths']['assets_dir']` into `output/cherry_pick.sh` (then
    `chmod +x`) instead of assembling it from hundreds of string-joined
    lines in Python. Falls back to the shipped `configs/assets/` default
    when `cfg['paths']` is absent or incomplete (e.g. hand-built cfg dicts
    in unit tests).
  - Only `cherry_pick_data.json` is generated; it embeds `target_rev` and
    `rev_new` alongside the ordered commit list so the script is fully
    self-contained.
  - Removed all in-Python script-text generation (`_build_cherry_pick_script`)
    and the short-lived companion-helper-script approach explored mid-session
    (`_HELPER_PY` / `cherry_pick_helper.py`) -- neither is needed once Python
    is embedded correctly via quoted heredocs.

- **lib/stages/st07_report.py** — updated to call the new `write_cherry_pick_files()` API.

- **tests/test_config.py** — added coverage for `paths.assets_dir`: default
  resolution to the shipped `configs/assets/`, absolute override, and
  `${CONFIGDIR}`-relative override resolution.

- **tests/test_cherrypick_script_gen.py** — rewritten for the copy-based design:
  - Asserts `output/cherry_pick.sh` is byte-identical to the resolved asset.
  - Validates the static asset with `bash -n`.
  - Adds real subprocess-level end-to-end tests: `--help`, no-args, invalid
    `--set`, and a full `git cherry-pick` run against a real temporary repo
    with a commit subject containing parentheses and mixed quotes.
  - Adds `paths.assets_dir` override coverage: default resolution, explicit
    override, and an end-to-end run confirming the overridden script (not
    the shipped default) is the one actually copied.

- **tests/test_st07_report.py** — integration tests check for `cherry_pick.sh`
  + `cherry_pick_data.json` (unchanged from the prior draft; still valid
  under the copy-based design).

- **run_tests** — added `export WORKSPACE=$(pwd)` for pytest compatibility.

- **MANIFEST.json** — updated outputs to reflect `cherry_pick.sh` +
  `cherry_pick_data.json`.

- **README.md** / **docs/CONFIGURATION.md** — rewrote the "Cherry-pick
  execution scripts" section to describe the static-asset-copy mechanism,
  the `paths.assets_dir` override, and the quoted-heredoc technique; added
  Testing section to README.md.

### Rationale

- A copied static script is easier to review, diff, and shellcheck than one
  assembled from generated string joins.
- `configs/assets/` cleanly separates "files copied verbatim into output/"
  from templated/generated config (profiles, rules, HTML templates).
- Resolving the asset through `paths.assets_dir` (same convention as
  `templates_dir`/`scoring_dir`) lets product configs customize or replace
  the script without touching the pipeline's own tree.
- Single source of truth for commit order (no duplication between two files).
- Boolean `relevant` flag is simpler than maintaining two separate arrays.
- `output/` folder can be exported/archived independently from `cache/`.
- Quoted heredocs + `sys.argv` let Python live directly inside the bash
  script with zero quoting fragility, without introducing a second file to
  maintain and ship alongside the script.

### Tests

All tests pass, including new end-to-end subprocess tests that execute the
copied script against a real git repository, and new `paths.assets_dir`
default/override coverage in both `lib.config` and `lib.cherrypick_script_gen`.

---

## v19.4.2 — feat: enhanced cherry-pick scripts with progress, logging, and branch prompt (2026-09-02)

### Added

- **Progress output in generated scripts** — each `git cherry-pick` call is now
  wrapped in a `cp_one()` bash function that prints:
  - `Commit <SHA> <n>/<max> - OK` in green on success
  - `Commit <SHA> <n>/<max> - FAIL` in red on failure (to stderr)

- **Centralized failure logging** — each script writes all failures to a single
  log file (`cherry_pick_prefiltered.log` or `cherry_pick_relevant.log`), with
  clear separators and full error output for each failing commit. The log file
  is recreated fresh on each run.

- **Branch creation prompt** — before starting, the script prompts:
  `Create local branch cherrypicking_from_<rev_new> before starting? [y/N]`
  If accepted, creates and switches to that branch; otherwise continues on the
  current branch.

### Changed

- **lib/cherrypick_script_gen.py** — replaced raw `git cherry-pick <sha>` lines
  with calls to a new `cp_one()` wrapper function that implements the progress
  output, colorization, and logging behavior described above.

- **tests/test_cherrypick_script_gen.py** — updated all script-content tests to
  expect `cp_one "<sha>"` calls instead of raw `git cherry-pick`, and added new
  tests verifying the presence of `LOGFILE=`, color codes (`GREEN=`, `RED=`,
  `NC=`), the branch prompt (`BRANCH_NAME=`, `read -p`, `git checkout -b`), and
  the progress format strings.

### Configuration

No config changes — purely an enhancement to the generated scripts' UX.

---
