# Changelog

All notable changes to this project will be documented in this file.

## v12.0.2 — prefilter: directory-scoped log-basename artifact evidence (2026-06-03)

### Fixed (C)

- `lib/stages/st04_prefilter.py` — `_file_has_artifact()` now scopes
  **log-derived basename matches** (`log_basenames`) to the file’s parent
  directory.

  **Root cause.** `build_compiled_sets()` populates `log_basenames` from
  `built_objects_from_log` by extracting *bare filename stems*
  (e.g. `hub` from `drivers/usb/hub.o`).  The previous implementation
  accepted any file whose basename stem was in that set, regardless of
  directory:
  ```python
  # BEFORE — too broad
  return bn_stem in cs['log_basenames']
  ```
  This meant a build-log entry for `drivers/usb/hub.o` also matched
  `sound/usb/hub.c`, `net/hub.c`, etc., causing large spurious
  over-keeping across unrelated subsystems.

  **Fix.** A log-basename hit is accepted only when the file’s parent
  directory is in `compiled_dirs` **or** the file itself is in
  `compiled_files`:
  ```python
  # AFTER — directory-scoped
  if bn_stem not in cs['log_basenames']:
      return False
  return (
      os.path.dirname(f) in cs['compiled_dirs']
      or f in cs['compiled_files']
  )
  ```
  `artifact_stems` (full-path stem matches from `built_artifacts_from_dir`)
  are precise and are not affected by this change.

  A detailed docstring has been added to `_file_has_artifact()` explaining
  both evidence sources, the scoping requirement, and the false-positive risk
  of unscoped basename matching.

### Tests (C)

- `tests/test_prefilter.py` — added 7 regression tests for the directory-
  scoped log-basename fix:

  | Test | Assertion |
  |---|---|
  | `test_file_has_artifact_log_match_requires_compiled_dir` | `sound/usb/hub.c` and `net/hub.c` NOT matched; `drivers/usb/hub.c` IS matched |
  | `test_file_has_artifact_log_match_requires_compiled_dir_deep` | Deeper paths scoped correctly |
  | `test_file_has_artifact_log_match_via_compiled_files` | Match accepted when file is in `compiled_files` |
  | `test_file_has_artifact_no_log_no_stem_returns_false` | File not in log_basenames returns False |
  | `test_log_basename_cross_tree_commit_not_kept` | End-to-end: `sound/usb/hub.c` reason ≠ `build_artifact` |
  | `test_log_basename_same_dir_commit_kept` | End-to-end: `drivers/usb/hub.c` reason == `build_artifact` |
  | `test_builtin_o_only_commit_dropped_when_kconfig_required` | Built-in.o commit not kept via artifact with kconfig active |

### Documentation (C)

- `docs/PIPELINE.md` — Stage 04 bullet updated to document both artifact
  evidence sources and the directory-scoping requirement; v12.0.2 changes
  section added.

### Version

- `MANIFEST.json` version bumped from `v12.0.1` → `v12.0.2`.

---

## v12.0.1 — prefilter: exclude kbuild placeholder aggregators (2026-06-03)

### Fixed (A)
- `lib/stages/st02_build_context.py` — `_scan_build_dir()` now skips
  **Kbuild directory-aggregator placeholders** (`built-in.o`, `built-in.a`).
  These files are synthetic intermediate linker inputs automatically produced
  by kbuild to merge directory-level objects for upward linking; they have no
  1-to-1 correspondence with any source file.
  Previously they entered `build_artifacts` in `build_context.json`, which
  caused stage 04’s L2½ `build_artifact` check to keep commits that should
  have been eliminated by the prefilter — resulting in insufficient commit
  reduction when a real build tree was provided.
- The set of excluded names is defined in the new constant
  `_KBUILD_PLACEHOLDER_NAMES` (currently `{'built-in.o', 'built-in.a'}`) so
  it can be extended and independently tested.

### Tests (A.2, A.3)
- `tests/test_st02_build_context.py` — added 6 regression tests:
  - `test_scan_build_dir_excludes_builtin_o` — `built-in.o` absent, real `.o` present
  - `test_scan_build_dir_excludes_builtin_a` — `built-in.a` absent, real `.o` present
  - `test_scan_build_dir_excludes_builtin_o_at_root` — exclusion at every depth
  - `test_scan_build_dir_only_builtin_returns_empty` — placeholder-only dir yields `[]`
  - `test_kbuild_placeholder_names_constant_contains_expected` — constant coverage
  - `test_run_builtin_o_excluded_from_build_artifacts` — end-to-end: JSON on disk clean
- `tests/test_prefilter.py` — added 4 regression tests:
  - `test_build_compiled_sets_builtin_o_not_in_artifact_stems` — documents artifact_stems behaviour
  - `test_builtin_o_only_commit_not_kept_by_artifact_evidence` — reason != `build_artifact`
  - `test_builtin_o_only_commit_dropped_when_kconfig_required` — reason != `build_artifact` after fix
  - `test_build_compiled_sets_builtin_o_not_in_artifact_stems` — stale-cache defensive check

### Documentation (A.4)
- `docs/PIPELINE.md` — Stage 02 bullet updated to explain placeholder exclusion;
  v12.0.1 changes section added.

### Version
- `MANIFEST.json` version bumped from `v12.0.0` → `v12.0.1`.

---

## v12.0.0 — stage-7 progress fix + evaluation sidebar (2026-06-02)

### Fixed (A.3)
- `lib/stages/st07_report.py` — `_update_stage7_progress()` now calls
  `update_stage_progress()` from `lib.pipeline_runtime` with the **correct
  argument signature**:
  ```
  update_stage_progress(stage_index, stage_total, frac, label,
                        n_done=current, n_total=total)
  ```
  Previously the call passed `current` (an int) as the `frac` positional
  argument and `total` (an int) as the `label` positional argument, which
  caused a `TypeError` on TTY terminals and sent meaningless values to the
  progress bar even when no exception was raised.
- Added `_STAGE7_MILESTONES` constant so the total milestone count is
  maintained in one place, shared by both `_update_stage7_progress()` and the
  final `finish_progress_line()` call.
- Added graceful `try/except` around the `_rt_progress` call so a
  mis-configured or unavailable pipeline_runtime never aborts report writing.

### Added (A.4)
- `_build_evaluation_block(cfg, ...)` helper builds an `evaluation` dict from
  `cfg` keys (`git`, `profiles.active`, `reports.top_n`, `filter.min_score`,
  `html_detail_mode`, enabled output formats) and stores it in `report_stats`.
  This block is forwarded to `generate_html_report()` and rendered in the
  **Evaluation** sidebar section, making the run parameters visible directly
  in the HTML report.

### Clarified (A.5 — no code change)
- Docstring of `_commit_rows()` updated to explain that the **Product Evidence
  cell is intentionally included** for CSV / XLSX / ODS outputs (matching
  `COMMIT_COLS`). The HTML table column exclusion is handled in
  `html_report.py`, not here.

### Tests
- `tests/test_st07_report.py` — added test
  `test_update_stage7_progress_calls_rt_progress_correctly` that verifies
  `_update_stage7_progress()` calls `_rt_progress` with:
  - positional args `(7, 7, <float frac>, <str label>)`
  - keyword args `n_done=current, n_total=total`
- Added assertion that `0.0 <= frac <= 1.0` is always satisfied.

### Version
- `MANIFEST.json` version bumped from `v11.3.2` → `v12.0.0`.

---

## v11.3.2 — report fixes, tests, and measured coverage (2026-05-12)

- HTML report sidecar flow refined: report metadata sidecar, sidecar table JSON, sharded commit details, and detail label normalization to `Evidence`.
- Main HTML report table no longer shows the `Product Evidence` column; commit detail views keep the shorter `Evidence` label.
- Added targeted regression tests for report generation, command behavior, manifest assertions, and stage-1 commit collection normalization.
- Measured test baseline established with coverage tooling: **465 tests passing**, **85%** total `lib/` coverage.
- Documentation updated in `docs/PIPELINE.md` for v11.3.2 report behavior and test/coverage status.

## v11.3.1 - 2026-05-11

### Fixed
- HTML report theme toggle button now works correctly in Firefox.
- Replaced SVG `innerHTML` injection with `createElementNS`-based DOM construction for the sun/moon icons, which is required for correct SVG manipulation in Firefox.
- Added `e.preventDefault()` to the theme button click handler to prevent spurious form/anchor interactions in strict-mode Firefox documents.

### Tests
- Added regression coverage verifying the theme toggle block uses `createElementNS` and not `innerHTML` for SVG icon updates.

## v11.3.0 - 2026-05-11

### Changed
- Switched HTML report table filtering from DOM-driven text extraction to precomputed per-row data arrays.
- Global search now reuses a cached lowercase haystack per row instead of rebuilding it from DOM cells on every filter pass.

### Performance
- This reduces repeated `textContent` reads during filtering and prepares the report UI for later pagination or worker-based filtering if needed.

### Tests
- Added regression coverage ensuring the report JS uses precomputed row data and cached haystacks for filtering.

## v11.2.9 - 2026-05-11

### Fixed
- Improved Firefox compatibility for HTML reports by replacing the filter busy overlay’s direct `color-mix()` dependency with a solid RGBA fallback plus guarded `@supports` enhancement.
- Hardened the client-side CSV download path with a fallback from synthetic `MouseEvent` dispatch to plain `a.click()` for browsers or sandbox contexts where synthetic click dispatch is unreliable.

### Tests
- Added regression coverage for the busy-overlay CSS fallback and the download click fallback logic.

## v11.2.8 - 2026-05-11

### Added
- HTML reports now show a waiter-style loading animation while table filters are being processed.
- The filter UI sets `aria-busy` on the table wrapper during filter work and uses a visible overlay spinner with status text.
- Filter execution is scheduled through `requestAnimationFrame` plus a zero-delay timeout so the browser can paint the loading state before heavy filtering starts.

### Tests
- Added regression coverage for the filter busy overlay in generated HTML, the busy-state scheduling logic in JS, and the spinner overlay styles in CSS.

## v11.2.7 - 2026-05-11

### Added
- HTML reports now support light and dark themes with a toggle button in the top header.
- The theme initialises from the system `prefers-color-scheme` preference and can be switched at any time using the header button.
- CSS `[data-theme]` overrides cover all colour tokens so the entire report — table, sidebar, detail pane, score pills — adapts consistently.

### Tests
- Added regression coverage for the theme toggle button in generated HTML, the JS toggle logic, and the CSS `[data-theme]` blocks.

## v11.2.6 - 2026-05-11

### Fixed
- Fixed HTML commit detail side pane opening and rendering across Chrome and Firefox by hardening delegated click handling and adding a fallback embedded commit-detail map for compressed reports.
- Added explicit error rendering in the side pane when commit-detail loading fails instead of leaving the pane blank.

### Tests
- Added regression coverage for compressed-report commit-detail fallback data and for cross-browser detail-pane event/error handling.

## v11.2.5 - 2026-05-11

### Fixed
- Improved HTML report compatibility with Firefox by using a safer client-side CSV download trigger and a fallback path for compressed embedded commit data when zlib decompression is unavailable or fails.

### Tests
- Added HTML report regression coverage for the Firefox-safe download path and embedded zlib fallback handling.

## v11.2.4 - 2026-05-10

### Added
- HTML commit reports now show a live counter for the currently visible commit rows after filtering.
- HTML commit reports now include a button to export the currently filtered visible rows as CSV.

### Tests
- Added HTML report regression coverage for the live counter and filtered CSV export button.

## v11.2.3 - 2026-05-10

### Fixed
- Added compatibility fallback for legacy external rule names such as `artemis_generic`, mapping them to shipped built-in equivalents during stage-0 rule compilation when no exact rule folder exists.
- Preserved precedence of exact external rule folders over built-in alias fallback.

### Tests
- Added regression coverage for `artemis_generic` fallback and for external exact-match precedence over the built-in alias fallback.

## v11.2.2 - 2026-05-10

### Fixed
- Always include shipped built-in rule directories as fallback during stage-0 rule compilation, so external profile overrides can still reference built-in rule folders such as `artemis_generic`.

### Tests
- Added regression tests covering built-in profile fallback and external profile overrides that continue to use shipped built-in rule folders.

## v11.2.1 - 2026-05-10

### Fixed
- Accepted singular `paths.rules_dir` and `paths.profiles_dir` aliases during stage-0 profile/rule compilation, so prepare_pipeline resolves runtime-derived path mappings consistently with config loading.

### Tests
- Added regression tests covering singular alias handling directly in `lib.profile_rules.compile_rules_for_config()` and revalidated the targeted QA set including the mini full-pipeline test.

## v11.2.0 - 2026-05-10

### Fixed
- Accepted the singular compatibility aliases `profiles_dir` and `rules_dir` in configuration files and normalized them to the internal `paths.profiles_dirs` and `paths.rules_dirs` list form.

### Tests
- Added unit tests covering `profiles_dir` and `rules_dir` config-file handling and revalidated the targeted QA set including the mini full-pipeline test.

## v11.1.0 - 2026-05-10

### Fixed
- Added fallback profile/rule lookup so external config trees can reuse built-in shipped profiles and rules without copying them locally.
- Preserved precedence of external profiles/rules over built-in shipped ones, avoiding false name-collision failures during stage 0 compilation.

### Tests
- Added coverage for built-in rule fallback and override precedence, and revalidated targeted QA including the mini full-pipeline test.

## Unreleased

## v10.2.1 — 2026-05-09

### Reporting and test-harness alignment
- Added a Profile Scores column to tabular report outputs and spreadsheet exports.
- Improved HTML sidecar detail loading by accepting realistic sidecar table payloads and normalized detail lookups.
- Added realistic end-to-end command and miniature-input regression tests under `tests/`.
- Updated README, `docs/*`, and the example config comments to align with current config keys, shipped profiles, and test assets.
- Full unit test suite passes: **422 tests, 0 failures**.

### Report scaling and ordering
- Added sidecar HTML table datasets and sharded per-commit detail JSON for scalable report loading.
- Added optional compressed embedded HTML commit payloads.
- Enforced canonical git-log-style ordering for detailed commit JSON outputs.

## v10.0.1 — 2026-05-09

### Validation compatibility fix
- Restored acceptance of loader-derived runtime fields in validation so `prepare_pipeline` no longer rejects `paths.profiles_dirs`, `paths.rules_dirs`, `paths.scoring_dir`, `paths.templates_dir`, `_meta`, or `config_dir`.
- Added a regression test covering the normalized config shape emitted by `load_config()`.

## v10.0.0 — 2026-05-09

### v10 pipeline contract cleanup
- Stage 04 now writes `prefilter_kept_commits.json` for commits that survive prefiltering and `filtered_commits.json` only for commits dropped during prefiltering.
- Stage 05 scores only `prefilter_kept_commits.json`, eliminating the old filtered/kept cache ambiguity.
- Stage 06 now writes threshold drops to `postfilter_dropped_commits.json` instead of mutating the prefilter-dropped cache.
- Stage 07 merges prefilter and postfilter dropped commits only when generating filtered output reports.

### Validation and schema tightening
- Added `lib/schema.py` to validate filtered and scored commit cache artifact shapes.
- Tightened configuration handling and validation toward the v10 strict-contract model, including rejection of unknown top-level keys.
- Updated stage tests and validation tests to cover the new cache split and stricter config behavior.

### Reporting and timestamp handling
- Updated report-generation paths to use the new cache split consistently.
- Reworked timestamp handling in report paths and spreadsheet export to avoid deprecated patterns while keeping generated files valid.

### Documentation and test suite
- Updated `README.md` and `docs/CONFIGURATION.md` to describe the v10 cache contract and config direction.
- Full test suite passes: **406 tests, 0 failures**.

- v10 cleanup in progress: strict config validation, explicit cache contracts, dedicated `postfilter_dropped_commits.json`, artifact schema validation, and timezone-aware UTC timestamp formatting.
- Fix stage-cache flow for filtered vs relevant generation: stage 04 now stores kept commits in `prefilter_kept_commits.json`, and stage 05 scores that cache instead of mistakenly reading `filtered_commits.json`. This ensures relevant commits come from prefilter-kept commits while filtered output remains the dropped set.

## v9.14.17 — 2026-05-09

### Filtered-commit output in all report formats (T.1 / T.2)
- `lib/stages/st07_report.py` — filtered commits are now written to the output
  folder alongside the scored-commit reports, in every enabled format:
  `filtered_commits.html`, `filtered_commits.csv`, `filtered_commits.xlsx`,
  `filtered_commits.ods`, and always `filtered_commits.json`.
- HTML dump reuses the same template pipeline as the main summary, with a
  dedicated `is_filtered=True` flag that makes the `Filter reason` column visible.
- All writes are guarded by `if filtered:` — no empty files are created.

### Test suite — Tier 1 / 2 / 3 (T.5 – T.13)
- 23 test files, **399 tests, 0 failures**, ~80 % line coverage.
