# Changelog

All notable changes to this project are documented in this file.

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
