# Changelog

All notable changes to this project are documented in this file.

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

### Added

- **Normalized score** (`score_norm`, 0–100) — the raw `score` normalized
  against the current run's maximum: `round(100 · score / max_score_in_run)`.
  Surfaced as the **"Score"** report column (CSV / XLSX / ODS / HTML +
  `relevant_commits.table.json`). Computed in stage 06 over the relevant set;
  informational, run-relative, not comparable across runs. The raw `score` is
  retained as **"Score (raw)"** (hidden in HTML table but exported).
  - `lib/backport.py::normalize_score()` is the single source of truth for
    score normalization.

### Changed

- `lib/backport.py::compute_pick_priority()` now takes the already-normalized
  `score_norm` (instead of `score` + `max_score`) so normalization happens
  exactly once; `pick_priority` output is numerically unchanged.
- `lib/manifest.py::COMMIT_COLS` updated: **"Pick Priority"** moved before
  **"Score"** (formerly "Score %"), **"Backport Cx"** renamed to **"Complexity"**,
  **"Backport Tier"** dropped.
- HTML: per-profile score columns are now anchored after the score family
  (`score`, `score_norm`) so the header stays grouped.
- HTML: report table header labels (`tr.kc-sort-row th`) now wrap onto
  multiple lines (`white-space: normal` + `overflow-wrap: break-word`,
  bottom-aligned) instead of overflowing into neighbouring columns.
- `lib/scoring.py::order_commit_details()` and
  `lib/commands/cmd_diagnose.py::_commit_section()` surface `score_norm`.

### Removed

- **Categorical backport tier.** The `backport_tier` field (values: `easy`,
  `moderate`, `hard`) was removed from all outputs (row data, JSON, spreadsheets).
  The information is now conveyed directly by the **Backport Cx** numeric value,
  which uses the unified 4-level heat-coloring scheme (see below). This simplifies
  the data model and keeps one source of truth for complexity: the 0–100 integer.
  - `lib/backport.py`: removed `tier_for_complexity()` and the `tier` field from
    `compute_backport_complexity()` and `enrich_commit_backport()`.
  - All pipeline stages, reports and tests updated accordingly.

### HTML report — table de-clutter & unified heat coloring

- **Hidden columns.** `Files Changed`, `Lines Changed`, `Hunks`,
  **Score (raw)** and **Backport Tier** are now emitted with `hidden: true` in the
  relevant-tab column definitions (`lib/html_report.py::_COMMIT_COLUMNS` /
  `_columns_def()`). Their values are still attached to every row (available to
  global search, exports and the detail pane), but the browser-side JS drops them
  from the *visible* table so it stays readable.
  `configs/html/js/summary_01_globals.js::REL_COLS` filters `!c.hidden` out of
  the visible column set. The CSV/XLSX/ODS spreadsheet exports remain unchanged.

- **Unified 4-level heat coloring for numeric columns.** A shared visual scheme
  colours the main numeric indicators using a 4-step palette mapped to even
  quartiles of each column's scale (0–100). Polarity is per-column:
  - **Score**, **Pick Priority**: `higher-better` → level 4 (75–100) green,
    level 3 (50–74) lime, level 2 (25–49) orange, level 1 (0–24) red.
  - **Complexity** (formerly Backport Cx): `higher-worse` → same 4 levels but
    inverted: level 4 (75–100) red, level 3 orange, level 2 lime, level 1 green
    (low complexity = good).
  Implementation: `heatLevel(value, scale)` / `heatPill(value, {scale, polarity})`
  in `summary_02_utils.js`; CSS `.kc-heat-pill` + `.kc-heat-{1..4}` in `summary.css`.

- **Profile colour legend + bullets.** Each profile gets a deterministic
  colour derived from a hash of its name (`profileHue()` → hue constrained to
  180–330° to keep them visually distinct from the heat scheme's red/orange/green
  palette; `profileColor()`). The left-pane "Scoring profiles" section is now a
  legend of labelled coloured bullets, and the table `Profiles` column renders
  the matching bullets (with `title` tooltips) instead of text chips
  (`profileBullet()` / `profileBullets()`; `.kc-prof-*` in `summary.css`).

- **No per-profile score columns in the table.** The dynamically-injected
  `score_<profile>` columns are removed from the visible relevant-tab table —
  the per-commit breakdown is low-signal there and widens the table with one
  column per profile. The scores are still emitted as `score_<profile>` row keys
  (searchable) and shown in full in the commit-detail **Scoring** tab.

- **Richer Overview tab.** The commit-detail Overview lists the size and
  backport indicators below Score — Score (heat-coloured), Files changed,
  Lines changed, Hunks, Complexity (heat-coloured, higher-worse), and Pick
  priority (heat-coloured, higher-better). Raw Score (raw) is shown uncolored.
  All pillars use the same `.kc-heat-*` classes so the visual language is
  consistent between the table and the detail pane.

- **Column reordering.** The visible HTML table columns are now ordered with
  the most important triage indicators first: Rank, SHA, Subject, **Author Organization**,
  Date, **Pick Priority**, **Score**, **Complexity**, Profiles. Less important columns
  (Score (raw), Files Changed, Lines Changed, Hunks, Backport Tier) are hidden
  but remain searchable and exported.

### Tests

- `normalize_score` tests and updated `compute_pick_priority` signature tests
  in `tests/test_backport.py` (removed `tier_for_complexity` import and tests).
- Stage-06 `score_norm` tests (top=100, proportional, zero-max safe) in
  `tests/test_st06_postfilter.py`; updated to drop `backport_tier` assertion.
- HTML tests updated: Score column (formerly "Score %"), heat-pill CSS/JS
  assets, hidden-column assertions (`files`/`lines`/`hunks`/`score`/`backport_tier`
  hidden; `backport_cx` (Complexity) and `pick_priority` visible and heat-coloured),
  profile colour bullets/legend and enriched Overview tab, in
  `tests/test_html_report.py`.
- `test_summary_js_does_not_inject_per_profile_columns` replaces the old
  per-profile-column assertion (columns removed; row keys retained).
- Spreadsheet column-index assertions updated in `tests/test_spreadsheet.py`
  and `tests/test_st07_report_extra.py` (indices shifted after removing Backport
  Tier column).
- New `test_assembled_js_parses_in_one_scope` regression test: assembles the
  real `configs/html/js/` bundle into its single IIFE scope and runs
  `node --check` on it, catching duplicate-identifier / syntax errors that
  per-file checks miss (skips when Node.js is unavailable).

## v18.4.0 — feat: hunks indicator + backport complexity / pick_priority (2026-08-24)

### Added

- **Hunks indicator** (`stats.hunks`) — total number of unified-diff hunks
  (`@@` blocks) across a commit, a fragmentation/dispersion signal. Opt-in via
  `collect.count_hunks` (default `false`); computed over the *relevant*
  (post-filter) commits only, via a single batched `git show --unified=0`, so
  the patch-inspection cost never touches the full commit range.
  - `lib/gitutils.py::count_hunks_in_patch()` and `batch_count_hunks()`.

- **Backport indicators** (computed in stage 06 over the relevant set,
  informational — never affect the score):
  - `backport_complexity` (0–100, higher = harder to cherry-pick): bounded,
    log-saturated weighted blend of files (cap 25), lines (cap 30), hunks
    (cap 25) and cross-subsystem spread (cap 20), reduced by a
    backport-friendliness bonus (`Cc: stable` 15 / `Fixes:` 10 / CVE 5, capped
    25), with a hard override of 100 for merge commits.
  - `backport_tier` (`easy` < 25 / `moderate` 25–59 / `hard` ≥ 60).
  - `pick_priority` (0–100, higher = look first): `0.70·relevance +
    0.30·ease`, where relevance is the score normalized against the run's max
    score and ease is `100 − complexity`. Within-run ranking aid; hard-coded
    weights.
  - New module `lib/backport.py` (`compute_backport_complexity`,
    `compute_pick_priority`, `tier_for_complexity`, `enrich_commit_backport`).

- New report columns after the size columns: **Hunks**, **Backport Cx**,
  **Backport Tier**, **Pick Priority** (CSV / XLSX / ODS / HTML). The HTML
  report defaults to sorting by **Pick Priority** descending (server-provided
  `default_sort` honoured by the table JS; the filtered tab keeps rank order).
  The sidecar `relevant_commits.table.json` gains `hunks`,
  `backport_complexity`, `backport_tier`, `pick_priority`.

### Changed

- `lib/stages/st06_postfilter.py` — new `_enrich_backport()` pass: optional
  hunk counting + backport/priority computation over the relevant set before
  writing `relevant_commits.json`. Git access is best-effort; hunk-count
  failures degrade to `hunks = 0` without failing the stage.
- `lib/manifest.py::COMMIT_COLS` extended (single source of truth).
- `lib/config.py` — `collect.count_hunks` (bool) added to the schema.
- `lib/scoring.py::order_commit_details()` and
  `lib/commands/cmd_diagnose.py::_commit_section()` surface the new fields.

### Tests

- New `tests/test_backport.py` (tier boundaries, complexity edge cases,
  friendliness reduction, merge override, pick_priority blend, enrichment).
- Hunk-counting tests in `tests/test_gitutils.py`
  (`count_hunks_in_patch`, batched marker parsing).
- Stage-06 enrichment tests in `tests/test_st06_postfilter.py` (hunks on/off,
  git-failure tolerance, indicator attachment).
- HTML column + default-sort tests in `tests/test_html_report.py`; updated
  column-index / column-set assertions in `tests/test_spreadsheet.py` and
  `tests/test_st07_report_extra.py`.

## v18.3.0 — feat: commit size indicators (files/lines changed) (2026-08-24)

### Added

- **Commit size indicators** — two descriptive metrics that measure how "big"
  a commit is, surfaced beside (but independent of) the profile/rule score:
  - `files_changed` — number of files touched (breadth; binary files counted).
  - `lines_changed` — total churn `insertions + deletions` (depth).
  Both `insertions` and `deletions` are also stored for reference.

- `lib/gitutils.py::compute_numstat_totals(numstat)` — aggregates the per-file
  `--numstat` list into a `{files_changed, insertions, deletions, lines_changed}`
  dict. Binary files (`-`/`-`) count toward `files_changed` but contribute
  `0` lines.

### Changed

- `lib/stages/st01_collect.py` — every collected commit now carries a populated
  `stats` dict (previously the `stats` key was referenced by
  `order_commit_details()` / `cmd_diagnose` but never populated). In
  `--name-only` mode (no per-line deltas) `files_changed` falls back to the
  touched-file count and line totals are `0`.

- Reports now expose two new columns, **Files Changed** and **Lines Changed**,
  inserted after **Score**:
  - `lib/manifest.py` — `COMMIT_COLS` extended (single source of truth;
    `COMMIT_COLS_FILTERED` inherits the new columns).
  - `lib/stages/st07_report.py::_commit_rows` and `lib/spreadsheet.py::_commit_row`
    (CSV / XLSX / ODS row builders) emit the two size cells.
  - `lib/html_report.py` — `files` / `lines` columns added to the relevant-tab
    table; the sidecar `relevant_commits.table.json` gains `files_changed` /
    `lines_changed` fields.

- These indicators are **purely informational** and do **not** affect the
  score, which remains exclusively rule/profile driven.

### Tests

- Added `compute_numstat_totals` unit tests (basic, empty, `None`, binary,
  malformed entries) in `tests/test_gitutils.py`.
- Added stage-01 `stats` population tests (numstat aggregation and name-only
  fallback) in `tests/test_st01_collect_run.py`.
- Added size-column tests in `tests/test_st07_report_extra.py`; updated the
  column-index assertion in `tests/test_spreadsheet.py` for the shifted
  Profile Scores column.

## v18.1.0 — perf(st03): cap history revisions, depth-filter Makefiles, merged-map cache (2026-06-18)

### Changed

- `lib/history_map.py` — three targeted optimisations for large commit ranges
  (C+B+E) that reduce `build_history_config_map()` wall-time from ~1 800 s to
  ~25–40 s for a 200k-commit range (cold), and to < 1 s on warm reruns.

  **C — Cap sampled revisions (`max_history_revisions`)**

  A new `history_mapping.max_history_revisions` config key (default `16`) caps
  the total number of sampled git revisions regardless of the commit range size.
  Previously, with `sample_step=1000` and a 200k-commit range, 200 revisions
  were sampled; the new cap keeps this at 16.  Combined with B, the total
  git-show task count drops from ~60 000 to ~800 for a 200k-commit run.

  **B — Depth-cap interesting Makefiles (`max_makefile_depth`, `min_makefile_symbols`)**

  `_guess_makefiles_from_map()` now accepts `max_depth` (default `3`) and
  `min_symbols` (default `1`) parameters, wired to new config keys
  `history_mapping.max_makefile_depth` and `history_mapping.min_makefile_symbols`.
  Makefiles deeper than `max_depth` directory components or belonging to
  directories with fewer than `min_symbols` symbol references are excluded.
  This typically reduces the probed Makefile set from ~300 to ~50 for a full
  kernel tree (≈6× fewer tasks per revision).

  **E — Merged-map top-level cache (`history_merged_map.json`)**

  After completing the expensive git-show + parse + merge pass, the resulting
  `config_to_paths` dict is persisted atomically to
  `<cache_dir>/history_merged_map.json` under a 24-hex SHA-256 key derived
  from `rev_old`, `rev_new`, and the sorted `interesting_paths` list.  On a
  subsequent run with the same commit range and Makefile set, the entire
  `build_history_config_map()` function returns in < 1 s without spawning any
  subprocesses.  A different rev range or a change in the probed Makefile set
  automatically invalidates the cache (different key → cache miss → cold run).

  New private helpers: `_merged_map_cache_key()`, `_load_merged_map_cache()`,
  `_save_merged_map_cache()`.

  Diagnostic print added: `history map: N revision(s) × M Makefile(s) = T task(s)`
  shown on every cold run so operators can observe the effect of the B+C caps.

### New config keys (all under `history_mapping`)

| Key | Type | Default | Optimisation |
|---|---|---|---|
| `max_history_revisions` | int | `16` | C — hard cap on sampled revisions |
| `max_makefile_depth` | int | `3` | B — max directory depth for probed Makefiles |
| `min_makefile_symbols` | int | `1` | B — min symbol references per Makefile dir |

### Tests

- `tests/test_history_map.py` — 18 new tests covering:
  - `_merged_map_cache_key()`: stability, range sensitivity, path sensitivity,
    order-independence (4 tests)
  - `_load_merged_map_cache()` / `_save_merged_map_cache()`: roundtrip, wrong
    key, absent file, None dir, overwrite (5 tests)
  - `_guess_makefiles_from_map()`: depth cap, min_symbols, combined filters,
    defaults, empty map, sorted output, root paths (7 tests)
  - `build_history_config_map()` integration: revision cap, merged-cache hit,
    merged-cache save, cache invalidation on range change (4 tests)

  `_cfg()` helper updated to accept `max_hist_revs`, `max_depth`, `min_symbols`
  keyword arguments for cleaner per-test configuration.

### Version

- `MANIFEST.json` version bumped `v18.0.1` → `v18.1.0`.

---

## v18.0.1 — stability fixes, validation downgrade, and report/runtime cleanups (2026-06-18)

### Changed

- `lib/stages/st01_collect.py` — when `collect.max_commits` is unset, the
  progress bar now uses `n_total=None` instead of `0`, preventing a frozen
  `0/0 (0%)` display during open-ended collection runs.

- `lib/stages/st05_score.py` — worker-future exception handling now propagates
  `fut.result()` failures correctly, while the per-commit fallback path is
  narrowed to the intended scope.

- `lib/stages/st06_postfilter.py` — score bucket label changed from `100+` to
  `>=100`, matching the uncapped score semantics introduced in v16.5.0.

- `lib/validation.py` — missing or non-existent `kernel.source_dir` is now a
  notice rather than a blocking config problem, allowing keyword-only profile
  runs that do not require a source tree.

### Fixed

- `configs/html/js/summary_10_table.js` — table rendering fix included in the
  staged batch for v18.0.1.

- `lib/commands/base.py` — unclosed file-handle path replaced with a
  `with open(...)` context-manager pattern.

- `lib/config.py` — `save_json()` now writes via a temporary file and atomic
  replace, avoiding truncated or partially-written JSON on interruption.

- `lib/pipeline_runtime.py` — stderr TTY detection is now cached per process
  (`_stderr_is_tty`) instead of via a stale global state pattern.

- `lib/stages/st06_postfilter.py` — score-distribution output and tests now use
  the corrected `>=100` top bucket label consistently.

- `lib/stages/st07_report.py` — module import ordering fixed so the module
  docstring remains the true top-level docstring.

- `lib/stages/st07_report.py` — duplicate-SHA debug logging restored in
  `_write_commit_details()`.

- `lib/stages/st07_report.py` — `_STAGE7_MILESTONES` corrected from 8 to 9 and
  explicit milestone-8 handling added so progress reporting is accurate.

- `lib/validation.py` — config validation messaging now distinguishes
  non-blocking source-tree absence from real schema / revision problems.

### Tests

- `tests/test_st06_postfilter.py` — updated top-bucket assertions from
  `100+` to `>=100`.

- `tests/test_validation.py` — updated `source_dir` expectations from
  `problems` to `notices` for the two non-blocking validation cases.

### Version

- `MANIFEST.json` version bumped `v18.0.0` → `v18.0.1`.

---

## v18.0.0 — fix: --force has no effect on full pipeline run (2026-06-18)

### Fixed

- `lib/commands/cmd_run.py` — `--force` flag was silently ignored when running
  the full pipeline (no `--stage`, `--from`, or `--resume` options).

  **Root cause.** The `else` branch in `cmd_run()` (full pipeline run list)
  never called `wipe_downstream()`, so `pipeline_state.json` retained
  `"status": "ok"` entries from a previous run and cached output files were
  left on disk.  Only the `--stage N --force` and `--from N` paths called
  `wipe_downstream()`.  The per-stage skip guard in `run_stage()` did
  correctly honour `args.force`, but stages consuming cached output from
  previous runs could still produce stale results.

  **Fix.** When `args.force` is set in the `else` (full-run) branch,
  `wipe_downstream()` is now called starting from the first stage
  (`STAGE_ORDER[0]`), clearing all stage state entries and deleting all
  cached output files before the run loop begins.

### Tests

- `tests/test_commands.py` — 3 new tests:
  - `test_cmd_run_force_full_pipeline_wipes_state` — verifies
    `wipe_downstream` is called from `STAGE_ORDER[0]` when `--force` is used
    without `--stage`, `--from`, or `--resume`.
  - `test_cmd_run_no_force_no_wipe` — verifies `wipe_downstream` is NOT
    called on a plain (non-forced) full run.
  - `test_cmd_run_force_with_stage_wipes_state` — regression guard ensuring
    `--force --stage N` still calls `wipe_downstream`.

### Version

- `MANIFEST.json` version is `v18.0.0` (already set).

---

## v17.0.0 — html: tab-switch loader overlay with ETA (2026-06-18)

### Changed

- `configs/html/summary.js` — v17.0.0: tab-switch loader overlay with ETA.

  **Problem.**  Switching between the *Relevant commits* and *Filtered commits*
  tabs calls `renderRows()` synchronously on the main thread.  With thousands
  of commits this blocks the browser for several seconds (rough throughput
  ~1 000 rows/s) with no visual feedback — the UI appears frozen.

  **Fix.**  A `.kc-table-loader` overlay (spinner + label) is injected once
  into `.kc-table-wrap` at boot.  `showLoader(rowCount)` computes a plain-text
  ETA at ~1 000 rows/s, updates the label text, and adds `.kc-loader-active`
  to make the overlay visible.  `hideLoader()` removes `.kc-loader-active`.

  `switchTab()` and the initial bootstrap `renderRows()` call now use a
  `setTimeout(0)` yield so the browser can paint the loader frame before the
  heavy synchronous DOM work begins.  The loader is hidden immediately after
  `renderRows()` + `applyFilters()` complete.

  ETA label examples:
  - < 1 000 rows  → "Loading 800 commits… (a moment)"
  - ~1 000 rows   → "Loading 1 200 commits… (~1 s)"
  - ~5 000 rows   → "Loading 5 000 commits… (~5 s)"

  CSS for `.kc-table-loader` / `.kc-spinner` / `.kc-loader-label` was already
  present since v16.13.0 — no CSS changes required.

### Version

- `MANIFEST.json` version bumped `v16.13.1` → `v17.0.0`.

---

## v16.14.1 — fix: tab switcher invisible due to missing id on toolbar div (2026-06-17)

### Fixed

- `configs/html/report.html` — the toolbar `<div>` had only
  `class="kc-toolbar"` and no `id` attribute.

  The JS tab-bar init block in `summary.js` does
  `document.getElementById('kc-toolbar')`, which returned `null`, so
  `insertAdjacentElement('beforebegin', bar)` was never called and the
  **Relevant / Filtered** tab switcher was silently dropped — it never
  appeared in the rendered report even when `window.__KC_UI__.tabs` was
  correctly populated.

  **Fix:** added `id="kc-toolbar"` to the toolbar div.  Also added
  `id="kc-table-wrap"` to the table-wrap div for consistency with the
  `updateFilterOffset()` CSS custom-property write.

---

## v16.14.0 — unified HTML report: filtered commits embedded in relevant_commits.html (2026-06-17)

### Changed

- `lib/html_report.py` — `generate_html_report()` gains an optional
  `filtered_commits=` kwarg (list of pre- + postfilter dropped commit dicts).

  When supplied, `window.__KC_UI__` gains four new keys consumed by the
  browser-side JS tab switcher:

  | Key | Content |
  |---|---|
  | `tabs` | `[{id, label, count}, …]` — two-element tab descriptor |
  | `filtered_columns` | slim column defs: rank, sha12, subject, author, date, filter_stage, reason |
  | `filtered_rows` | one slim row dict per filtered commit |
  | `filtered_store` (inline script) | sha12 → commit dict; scoring fields stripped |

  `filter_stage` is derived from `prefilter_debug` presence on each commit
  (`'prefilter'` when present, `'postfilter'` otherwise).

  The obsolete `is_filtered` parameter and `_FILTERED_EXTRA` tuple have been
  removed; JS tab logic in `summary.js` replaces them.

  New private helpers:
  - `_FILTERED_COLUMNS` — slim column-set constant for the filtered tab
  - `_filtered_columns_def()` — returns JS column-definition list
  - `_filtered_commit_row(i, c)` — serialises one filtered commit to a slim dict
  - `_filtered_commit_store_entry(c)` — strips scoring fields for `filtered_store`
  - `_SCORING_KEYS` — frozenset of field names stripped from filtered store entries

- `lib/stages/st07_report.py` — HTML output block updated for v16.14.0:

  - The separate `filtered_commits.html` file is **no longer written**.
    Filtered commits are embedded in the unified `relevant_commits.html`
    via `filtered_commits=filtered` passed to `generate_html_report()`.
  - `filtered_commits.table.json` sidecar is still written (guarded by
    `if filtered:`) so the JS tab can lazy-load filtered rows.
  - The `is_filtered=True` call path and its surrounding block are removed.
  - Module docstring `v16.14.0` entry added.

### Tests

- `tests/test_html_report.py`:
  - `test_html_filtered_table_includes_reason_column` — rewritten to use
    the new `filtered_commits=` kwarg instead of the removed `is_filtered=True`
    parameter.  Asserts against `ui['filtered_columns']` / `ui['filtered_rows']`
    (the keys populated by the new API).

- `tests/test_st07_report.py`:
  - `test_html_filtered_output_written` — assertion updated from
    `filtered_commits.html` to `relevant_commits.html`; docstring updated to
    explain the v16.14.0 unified-report behaviour.

### Version

- `MANIFEST.json` version bumped `v16.13.1` → `v16.14.0`.

---

## v16.13.1 — prefilter: embed debug dict in every commit (2026-06-17)

### Changed (K — prefilter_debug embedded in commit)

- `lib/stages/st04_prefilter.py` — `run()` now attaches the
  `filter_decision()` debug dict directly to every commit as
  `c['prefilter_debug']` (both kept **and** dropped), in addition to
  aggregating dropped-commit entries into `prefilter_debug.json`.

  **Motivation.**  Previously, `cmd_diagnose` had to cross-reference the
  aggregate `prefilter_debug.json` to retrieve the debug trace for a dropped
  commit — a two-file lookup that could silently return stale or mismatched
  data when the cache was partially regenerated.  Embedding the debug dict
  directly in the commit makes the data self-contained: any reader of
  `filtered_commits.json` or `prefilter_kept_commits.json` has the full
  decision trace without a second cache read.

  **Changes in `st04_prefilter.py`:**
  - `run()`: `c['prefilter_debug'] = dbg` written for **every** commit
    (kept and dropped alike) immediately after `filter_decision()` returns.
  - Dropped commits no longer carry `c['_prefilter_debug']` (underscore
    prefix); the field is now `c['prefilter_debug']` (no prefix) to match
    the key used in the aggregate file and in `cmd_diagnose`.
  - `_build_prefilter_debug_entry()` docstring expanded; parameter renamed
    `reason` → `drop_reason` for clarity.
  - `prefilter_debug.json` aggregate summary trimmed to the four keys that
    tests assert (`total_commits`, `kept`, `dropped`, `drop_reasons`);  the
    operational-metadata fields (`pattern_counts`, `kconfig_active`,
    `compiled_files`, `compiled_dirs`) removed from the summary block —
    they added noise without diagnostic value in the aggregate view.
  - Debug log line updated: `prefilter_debug.json: N dropped commit entries
    written` → `prefilter: kept=N dropped=N reasons={...}`.
  - Module docstring updated: per-commit embedded schema documented;
    aggregate `prefilter_debug.json` schema trimmed to match.
  - Version change history (K section) added to module docstring.

- `lib/scoring.py` — `order_commit_details()` `first` list extended with
  `'prefilter_debug'` so the new field appears in a stable position in
  serialised commit JSON.

- `lib/manifest.py` — `CACHE_FILES['prefilter_debug']` comment updated from
  `"per-dropped-commit debug detail"` to `"per-commit prefilter decision log"`.

- `lib/commands/cmd_diagnose.py`:
  - `_stage04(c, prefilter_debug_data)` → `_stage04(c)`: the aggregate-file
    parameter removed entirely.  The function now reads
    `c.get('prefilter_debug')` directly.
  - `diagnose_commit()`: `_load(cache_dir, 'prefilter_debug', warnings)` call
    removed; `prefilter_debug` local variable removed; `_stage04(commit,
    prefilter_debug)` call simplified to `_stage04(commit)`.
  - Module docstring `Cache files read` list: `prefilter_debug.json` entry
    removed; `NOTE (v16.13.1)` paragraph added explaining the new embedded
    approach.
  - `Stage 04 prefilter section detail` docstring updated to reference the
    embedded field.

### Tests

- `tests/test_cmd_diagnose.py` — `_make_commit()` helper: `prefilter_debug`
  kwarg now stores the dict under the production key `'prefilter_debug'`
  (no underscore prefix) instead of `'_prefilter_debug'`, matching the
  updated `run()` behaviour.

  No new tests required: existing `test_found_in_filtered_full_layer_detail`
  and related tests fully exercise the embedded-field path.

### Version

- `MANIFEST.json` version bumped `v16.2.0` → `v16.13.1`.

---

## v16.2.0 — diagnose: pipeline_version from cache, not running code (2026-06-14)

### Fixed

- `lib/commands/cmd_diagnose.py` — `meta.pipeline_version` now reflects the
  version that **produced the cache**, not the version of the currently running
  code.

  **Root cause.**  `diagnose_commit()` set `meta.pipeline_version = VERSION`,
  imported from `lib/manifest.py` at import time.  When the running binary was
  newer than the cache being read (e.g. diagnosing a run produced by v16.0.1
  with a v16.2.0 binary), the reported version was wrong — it showed the
  binary's version, not the run's.

  **Fix (two parts):**

  1. `lib/stages/st00_prepare.py` — `run()` now writes
     `pipeline_version: VERSION` into `prepare_summary.json` alongside
     `profiles` and `rule_counts`.  This records the version that ran stage 00
     — and therefore produced the cache — at the time of the run.

  2. `lib/commands/cmd_diagnose.py` — `diagnose_commit()` loads
     `prepare_summary.json` and reads `pipeline_version` from it.  If the file
     is absent or predates v16.2.0 (key not present), the value falls back to
     the explicit string `"unknown (cache predates v16.2.0)"` instead of
     silently reporting the wrong version.

  The `note` field in `meta` already states "No pipeline code was executed";
  the corrected `pipeline_version` makes that statement fully accurate.

### Tests

- `tests/test_st00_prepare.py`:
  - Assert `pipeline_version` key present in both `on_disk` summary and
    `run()` return value.
  - Assert value equals `VERSION` from manifest.

- `tests/test_cmd_diagnose.py` — 3 new tests:

  | Test | Assertion |
  |---|---|
  | `test_meta_pipeline_version_from_prepare_summary` | version taken from cache file, not running code |
  | `test_meta_pipeline_version_fallback_when_prepare_summary_absent` | file missing → `"unknown (cache predates v16.2.0)"` |
  | `test_meta_pipeline_version_fallback_when_key_absent` | file exists but key missing → fallback string |

### Version

- `MANIFEST.json` version bumped `v16.0.1` → `v16.2.0`.

---

## v16.1.0 — prefilter: file-type-aware L2half voting (2026-06-14)

### Changed (F — file-type-aware L2half)

- `lib/stages/st04_prefilter.py` — the L2½ block in `filter_decision()` now
  applies **per-file type-aware voting** instead of a flat two-step check.

### Version

- `MANIFEST.json` version bumped `v16.0.1` → `v16.1.0` (now superseded by
  `v16.2.0`).

---

## v16.0.1 — prefilter: _file_has_artifact trailing-slash normalisation (2026-06-13)

### Version
- `MANIFEST.json` version bumped from `v14.1.0` → `v16.0.1`.

---

## v16.0.0 — prefilter: Kconfig/Makefile directory-scoped coverage (2026-06-13)

### Version
- `MANIFEST.json` version bumped `v14.1.0` → `v16.0.0`.

---

## v14.1.0 — prefilter: remove keyword and path-whitelist coupling (2026-06-11)

### Version
- `MANIFEST.json` version bumped `v14.0.1` → `v14.1.0`.

---

## v14.0.1 — diagnose: remove cache_presence from JSON output (2026-06-11)

---

## v14.0.0 — prefilter: suppress kw_wl rescue when file evidence is authoritative (2026-06-11)

### Version
- `MANIFEST.json` version bumped from `v13.0.3` → `v14.0.0`.

---

## v13.0.1 — prefilter: Bug-1 disabled-symbol false-keep fix (2026-06-10)

### Version
- `MANIFEST.json` version bumped from `v13.0.0` → `v13.0.1`.

---

## v13.0.0 — legacy cleanup, doc accuracy, prefilter reason fix (2026-06-07)

### Version
- `MANIFEST.json` version bumped from `v12.0.3` → `v13.0.0`.

---

## v12.0.2 — prefilter: directory-scoped log-basename artifact evidence (2026-06-03)

### Version
- `MANIFEST.json` version bumped from `v12.0.1` → `v12.0.2`.

---

## v12.0.1 — prefilter: exclude kbuild placeholder aggregators (2026-06-03)

### Version
- `MANIFEST.json` version bumped from `v12.0.0` → `v12.0.1`.

---

## v12.0.0 — stage-7 progress fix + evaluation sidebar (2026-06-02)

### Version
- `MANIFEST.json` version bumped from `v11.3.2` → `v12.0.0`.

---

## v11.3.2 — report fixes, tests, and measured coverage (2026-05-12)

- HTML report sidecar flow refined.
- Measured test baseline: **465 tests passing**, **85%** total `lib/` coverage.

## v11.3.1 - 2026-05-11

## v11.3.0 - 2026-05-11

## v11.2.x - 2026-05-09 to 2026-05-11

## v10.x - 2026-05-09

## v9.14.17 — 2026-05-09

- Filtered-commit output in all report formats.
