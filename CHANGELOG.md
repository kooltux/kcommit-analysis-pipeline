# Changelog

All notable changes to this project are documented in this file.

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

### Added

- **Cherry-pick test indicator** (`cherry_pickable`) — opt-in actual `git cherry-pick`
  test onto `kernel.rev_old` for each relevant commit. When enabled via
  `collect.cherry_pick_test: true`, the pipeline runs `git cherry-pick --no-commit`
  for each relevant commit and records the result:
  - `"Yes"` — commit cherry-picks cleanly without conflicts
  - `"No"` — commit has conflicts when cherry-picked
  - `""` (empty) — test not run (feature disabled or commit not in relevant set)
  Surfaced as **"Cherry-Pickable"** column in HTML table (filterable), CSV, XLSX,
  ODS, and `relevant_commits.json`/`relevant_commits.table.json`. Full details
  (conflict file list, error messages) are stored in `cherry_pick_info` field in the
  JSON outputs. Implemented in `lib/gitutils.py` (`can_cherry_pick()`,
  `batch_can_cherry_pick()`) and integrated into stage 06.
  - `lib/gitutils.py`: new `can_cherry_pick()` (single commit) and
    `batch_can_cherry_pick()` (multiple commits with cleanup between tests) functions.
  - `lib/stages/st06_postfilter.py`: `_enrich_backport()` extended to run
    cherry-pick tests when `collect.cherry_pick_test` is enabled.
  - `lib/manifest.py::COMMIT_COLS`: added **"Cherry-Pickable"** column.
- **Author Organization column.** The **"Author"** column is replaced by
  **"Author Organization"** in the HTML table and spreadsheet exports (CSV, XLSX,
  ODS, `relevant_commits.table.json`). The organization is derived from the domain
  part of the commit's `author_email` (the substring after '@'). This allows
  reviewers to quickly identify the company or entity behind each commit at a glance.
  The commit-detail pane shows all author information: Author (name), Author Email,
  and Organization. The raw `author_name` and `author_email` fields are also retained
  in the JSON exports.

### Configuration

- New `collect.cherry_pick_test` option (default: `false`) — enable to run
  actual cherry-pick tests. **Warning**: This is expensive as it requires
  git worktree manipulation (checkout, cherry-pick, cleanup) for each relevant
  commit. Only enable when you need definitive conflict detection and have
  time for the extra runtime.

---

## v18.5.0 — feat: normalized score (Score %) indicator + unified heat coloring (2026-08-25)
