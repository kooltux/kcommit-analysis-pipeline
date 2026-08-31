# Changelog

All notable changes to this project are documented in this file.

## v19.2.3 — fix: stream cherry-pick results to database as they complete (2026-08-31)

### Fixed

- **Cherry-pick results now visible in database during testing** —
  `lib/gitutils.py::batch_can_cherry_pick()` and its internal helpers
  (`_cp_test_serial()`, `_cp_test_parallel()`) now accept a
  `result_callback(sha, result)` parameter that is called for each completed
  test. `lib/gitutils.py::batch_can_cherry_pick_cached()` passes a callback
  that immediately inserts each result into the SQLite cache via
  `lib/cherrypick_db::CherryDB.add_result()`. This ensures external queries
  like `sqlite3 cherry.db "SELECT COUNT(*) FROM commits"` see increasing
  counts (100, 200, 300...) during cherry-pick testing instead of 0 until
  completion.

- **CherryDB removed result buffering** — `lib/cherrypick_db.py::CherryDB`
  now flushes immediately after each `add_result()` call, ensuring writes are
  visible to external queries. The auto-save timer (5s) and batch threshold
  (20 results) are kept as safety mechanisms but are no longer the primary
  flush trigger.

- **Corrected v19.2.2 changelog claims** — the previous v19.2.2 entry claimed
  that disabling WAL mode and using autocommit would make rows visible during
  testing, but the actual control-flow defect was that
  `batch_can_cherry_pick_cached()` accumulated all results in memory and only
  inserted them after testing completed. This is now fixed by streaming
  results as they complete.

### Changed

- **Streaming architecture** — cherry-pick test results flow through a callback
  chain: `can_cherry_pick()` → `_cp_test_serial()`/`_cp_test_parallel()` →
  `batch_can_cherry_pick()` → `batch_can_cherry_pick_cached()` →
  `CherryDB.add_result()`. This enables real-time database updates without
  blocking the test loop.

- **Simplified CherryDB** — removed complex transaction management; each
  INSERT OR REPLACE is auto-committed in autocommit mode with WAL disabled.

### Tests

- Unit tests needed for:
  - `test_gitutils.py`: verify `result_callback` is called for each SHA in
    both serial and parallel modes
  - `test_cherrypick_db.py`: verify `add_result()` flushes immediately
  - Integration test: verify external SQLite queries see increasing counts
    during `batch_can_cherry_pick_cached()`

---

## v19.2.2 — fix: CherryDB disables WAL mode for immediate visibility (2026-08-31)

### Fixed

- **CherryDB now disables WAL mode for immediate write visibility** —
  `lib/cherrypick_db.py::CherryDB` now executes `PRAGMA journal_mode=DELETE`
  to disable WAL (Write-Ahead Logging) mode. WAL mode keeps writes in a
  separate `.wal` file and requires a checkpoint to make them visible to
  other database connections. By using DELETE mode (traditional rollback
  journal), each `INSERT OR REPLACE` is immediately visible to external
  SQLite queries.
  - Removed explicit `BEGIN IMMEDIATE` / `COMMIT` transactions
  - In autocommit mode, each INSERT is its own transaction committed immediately
  - External queries like `sqlite3 cherry.db "SELECT COUNT(*) FROM commits"`
    now show increasing counts (100, 200, 300...) during cherry-pick testing

- **Previously, rows were invisible until connection closed** — WAL mode was
  keeping writes in the WAL file without checkpointing, causing external
  queries to see 0 rows until the database connection closed. Now each row
  is immediately visible as it's inserted.

### Changed

- **Simplified transaction handling** — removed explicit transaction control;
  autocommit mode with one INSERT per transaction provides immediate visibility
  without needing explicit commits.

---

## v19.2.1 — fix: compute actual hunk counts for backport_complexity (2026-08-29)

### Fixed

- **Hunk counts now properly populated** — `lib/gitutils.py::compute_numstat_totals()`
  now returns a `hunks` field (initially `0` as placeholder), and
  `lib/stages/st01_collect.py` calls `batch_count_hunks()` after collecting
  commits to populate actual hunk counts for all commits. This fixes the
  `backport_complexity` calculation in `lib/backport.py` which uses `hunks_pts`
  as one of the four weighted factors (along with files, lines, and spread).
  Previously the `hunks` field was missing from stats, causing all `hunks_pts`
  calculations to be 0.

- **HTML UI shows 0 instead of N/A for missing stats** — `configs/html/js/summary_13_detail.js`
  now displays `0` instead of `N/A` when stats fields are null, providing a
  clearer indication that the value is zero rather than unavailable.

### Changed

- **Hunk counting always enabled** — `batch_count_hunks()` is now called for
  all commits in stage 01, using a single batched `git show --unified=0` call
  for efficiency. The hunks field is populated with actual diff hunk counts
  before backport_complexity is computed in stage 06.

### Tests

- `tests/test_gitutils.py`: updated all `test_compute_numstat_totals_*` tests
  to expect `'hunks': 0` in the output dict.
- `tests/test_st01_collect_run.py`: updated tests to expect `'hunks': 0` in
  commit stats (placeholder value before `batch_count_hunks()` populates actual
  counts).

---

## v19.2.0 — cp-check subcommand + config validation (2026-08-28)

### Added

- **Standalone `cp-check` subcommand** (`lib/commands/cmd_cp_check.py`) —
  replaces the previously generated `output/cherry_pick_check.py` script.
  Running the real `lib.gitutils` logic directly (instead of an embedded copy
  baked into a generated file) eliminates the risk of the two implementations
  drifting apart. The command always runs regardless of `collect.cherry_pick_test`
  config flag — it's an explicit, on-demand tool to check cherry-pick feasibility
  for the current prefilter commit set.
  - Reads commits from `cache/prefilter_kept_commits.json` (stage 04 output)
  - Uses the same SQLite cherry-pick cache as the pipeline (`CherryDB`)
  - Supports `--force` to wipe cache and retest all, `--json` for machine output,
    `--verbose` for per-commit status
  - Requires `collect.cherry_pick_cache_dir` and `kernel.rev_old` in config

- **Config variable validation** (`lib/config.py::load_config()`) — critical
  variables (`WORKSPACE`, `TOOLDIR`, `CONFIGDIR`, `CWD`) are now validated to
  be non-empty after expansion. If any critical variable is empty, the loader
  raises a clear `SystemExit` error telling the user to set the environment
  variable or define it in the config `"vars"` section. This prevents silent
  path corruption (e.g., `/cache` instead of `/path/to/work/cache`) when
  environment variables are unset.

### Changed

- **Cherry-pick feasibility moved to stage 05** — the `cherry_pickable` field
  is now computed in `lib/stages/st05_score.py::score_commit()` using
  `batch_can_cherry_pick_cached()` instead of being computed inline in stage 06.
  This centralizes cherry-pick logic in the scoring stage and removes the
  dependency on stage 06 for this feature.

- **Backport indicators computed inline in stage 06** — `score_norm`,
  `backport_complexity`, and `pick_priority` are now computed directly in
  `lib/stages/st06_postfilter.py::run()` after loading scored commits, instead
  of via a separate `_enrich_backport()` helper function. This simplifies the
  code and removes an unnecessary abstraction layer.

### Removed

- **Generated `output/cherry_pick_check.py` script** — replaced by the
  `cp-check` subcommand. The `_generate_cherry_pick_check_script()` function
  in `lib/stages/st06_postfilter.py` has been removed along with all related
  tests.

- **`_enrich_backport()` helper function** — its logic has been inlined into
  `run()` in `lib/stages/st06_postfilter.py`. Tests for this function have
  been removed from `tests/test_st06_postfilter.py`.

### Fixed

- **cp-check command path resolution** — fixed to use `cfg['paths']['cache_dir']`
  (with fallback to constructing from `work_dir`) instead of looking in
  `output_dir`. The prefilter_kept_commits.json file is written to the cache
  directory by stage 04, not the output directory.

### Tests

- `tests/test_st06_postfilter.py`: removed tests for `_enrich_backport()` and
  `_generate_cherry_pick_check_script()`; updated module docstring to reflect
  v19.2.0 changes.

---

## v19.1.0 — cherry-pick engine rewrite + SQLite caching + feasibility UI (2026-08-28)

### Changed

- **Cherry-pick test engine rewritten for correctness and speed.**
  `lib/gitutils.py::can_cherry_pick()` no longer uses
  `git cherry-pick --dry-run` (which required grepping stdout/stderr text for
  the word "conflict" — an unreliable heuristic). It now runs
  `git show | git apply --check --3way --unidiff-zero` and checks the
  subprocess **return code** directly: `rc == 0` means the patch applies
  cleanly, any non-zero code means conflict, with conflicted file paths
  parsed from `git apply`'s structured error output. This is also
  substantially faster, since `git apply --check` never touches the working
  tree or index (unlike a real cherry-pick attempt).
  - `batch_can_cherry_pick()` gained per-commit timing and a rolling-average
    ETA passed to `progress_callback(done, total, eta_seconds)`.

### Added

- **SQLite-based cherry-pick cache** (`lib/cherrypick_db.py::CherryDB`) —
  results are cached per target revision (`<cherry_pick_cache_dir>/<rev_old>/cherry.db`)
  so that incremental runs against the same `rev_old` only test *new* commits,
  reusing cached results for everything already tested. Since released kernel
  history is immutable, this cache never goes stale for a given target
  revision. Typical speedup: 10–100x on incremental runs.
  - `add_result()` buffers per-commit results and auto-flushes to disk every
    `AUTO_SAVE_INTERVAL` (5s) so long-running batch tests do not lose all
    progress if interrupted; `save()` performs a final flush before closing.
  - `lib/gitutils.py::batch_can_cherry_pick_cached()` is the new entry point
    used by the pipeline: loads/creates the per-target `CherryDB`, tests only
    uncached SHAs (with a live progress bar + ETA to stdout), then merges
    fresh and cached results.
  - `collect.cherry_pick_cache_dir` (path) is now a **required** config key
    whenever `collect.cherry_pick_test` is enabled; `batch_can_cherry_pick_cached()`
    raises `RuntimeError` with a corrective message if it is missing.
    Documented with example paths and speedup rationale in
    `configs/example-arm-embedded-full.json`.
  - `lib/config.py::CONFIG_SCHEMA['collect']` gained the
    `cherry_pick_cache_dir: {'type': 'path'}` entry.

- **Standalone `output/cherry_pick_check.py` generator kept in sync.**
  `lib/stages/st06_postfilter.py::_generate_cherry_pick_check_script()` emits
  a re-runnable checker script whose `can_cherry_pick()` implementation now
  matches the library version exactly (patch piped via `subprocess.run(...,
  input=patch)`, never as a bare argument). The generated script reads/writes
  the same SQLite cache as the main pipeline (reuse by default) and accepts a
  new `--refresh` flag to force re-testing every commit and overwrite the
  cache.

- **HTML report — cherry-pick feasibility sidebar.**
  `lib/html_report.py::_sidebar_payload()` gained an optional `commits=`
  kwarg; when any commit carries a non-`None` `cherry_pickable` flag, a
  `cherry_pick` block (`total_commits` / `cherry_pickable` / `cherry_pick_conflicts`)
  is added to the sidebar payload. `configs/html/js/summary_07_sidebar.js`
  renders this as a **"Cherry-pick feasibility"** stat block — `Tested` /
  `Direct` / `Conflict` counts with percentages — nested directly under the
  existing Pipeline Funnel "Commit flow" section.
  - `configs/html/js/summary_13_detail.js`: commit-detail Overview tab shows
    a `Cherry-pick` row with a ✔️ Yes / ✖️ No pill whenever `cherry_pickable`
    is not null.
  - `configs/html/summary.css`: new `--cherry-easy-bg/fg` and
    `--cherry-hard-bg/fg` design tokens (light + dark themes) backing the new
    `.kc-cherry-pill` / `.kc-cherry-easy` / `.kc-cherry-hard` classes.
  - HTML table column label shortened to **"CP-able"**.

### Fixed

- `lib/gitutils.py::can_cherry_pick()` previously never inspected the git
  subprocess return code, relying entirely on substring matching against
  command output — a latent correctness bug masked by the fact that
  `--dry-run` cherry-pick text usually (but not always) contained the word
  "conflict" on failure. The rewritten return-code check removes this class
  of false negative/positive entirely.

### Removed

- `configs/html/UI_V2_HANDOFF.md` — an abandoned handoff spec for a "v2" HTML
  UI redesign (overlay drawers, thead-outside-scroll-container virtual
  scrolling) that was never built. Deleted as dead planning documentation;
  the shipped UI remains the one described elsewhere in this changelog.

### Tests

- `tests/test_gitutils.py`: cherry-pick tests rewritten to mock
  `subprocess.run()` directly (patch + apply --check call sequence) instead
  of the old single mocked `run_git()` dry-run call.
- `tests/test_st06_postfilter.py`: cherry-pick enrichment tests updated to
  mock `batch_can_cherry_pick_cached()`; new tests cover standalone
  `cherry_pick_check.py` script generation (enabled/disabled/empty-commits
  cases).
- `tests/test_html_report.py`: new
  `test_html_report_sidebar_has_cherry_pick_block_when_tested` and
  `test_html_report_sidebar_omits_cherry_pick_block_when_not_tested`.

---

## v18.6.0 — feat: cherry-pick test indicator (2026-08-27)
