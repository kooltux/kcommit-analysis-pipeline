# Changelog

All notable changes to this project are documented in this file.

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
  ~1 000 rows/s) with no visual feedback — the UI appears frozen.

  **Fix.**  A `.kc-table-loader` overlay (spinner + label) is injected once
  into `.kc-table-wrap` at boot.  `showLoader(rowCount)` computes a plain-text
  ETA at ~1 000 rows/s, updates the label text, and adds `.kc-loader-active`
  to make the overlay visible.  `hideLoader()` removes `.kc-loader-active`.

  `switchTab()` and the initial bootstrap `renderRows()` call now use a
  `setTimeout(0)` yield so the browser can paint the loader frame before the
  heavy synchronous DOM work begins.  The loader is hidden immediately after
  `renderRows()` + `applyFilters()` complete.

  ETA label examples:
  - < 1 000 rows  → "Loading 800 commits… (a moment)"
  - ~1 000 rows   → "Loading 1 200 commits… (~1 s)"
  - ~5 000 rows   → "Loading 5 000 commits… (~5 s)"

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
  binary’s version, not the run’s.

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
