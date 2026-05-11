# Changelog

All notable changes to this project will be documented in this file.

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
- Improved Firefox compatibility for HTML reports by replacing the filter busy overlay's direct `color-mix()` dependency with a solid RGBA fallback plus guarded `@supports` enhancement.
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
- Updated stage tests and validation tests to cover the new cache contract and stricter config behavior.

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
- **Tier 1** (173 tests): `test_config`, `test_pipeline_runtime`,
  `test_prefilter`, `test_scoring`, `test_spreadsheet`, `test_st04_prefilter_run`,
  `test_st05_score_run`, `test_st06_postfilter`, `test_st07_report`,
  `test_parse_kconfig`, `test_kbuild`, `test_logsetup`, `test_validation`.
- **Tier 2** (57 tests): `test_st02_build_context`, `test_spreadsheet_extra`,
  `test_scoring_extra`, `test_st07_report_extra`.
- **Tier 3** (81 tests): `test_gitutils` (all git helpers via mocked subprocess),
  `test_st03_product_map`, `test_history_map` (gitshow disk-cache roundtrip +
  `build_history_config_map`), `test_commands` (`cmd_validate`, `cmd_status`,
  `cmd_dropped`, `cmd_report`, base helpers).
- Deferred (T.14): `datetime.utcfromtimestamp()` deprecation warnings in
  `spreadsheet.py`, `st07_report.py`, `html_report.py` — non-blocking, logged
  for next maintenance cycle.

## v9.13.0

### Documentation & config consistency audit (H, I)

#### Documentation fixes (H)
- H.1: `README.md` — outputs table replaced deprecated `templates.xls_output` /
  `templates.ods_output` references with canonical `reports.outputs` form.
- H.2: `README.md` — stage table separator row widths corrected.
- H.3: `docs/CONFIGURATION.md` — duplicate `reports` section merged into one,
  covering all four keys: `title`, `outputs`, `top_n`, `min_score`.
- H.4: `MANIFEST.json` — stage 0 output filenames corrected from
  `cache/00_compiled_rules.json` / `cache/00_prepare_summary.json` to
  `cache/compiled_rules.json` / `cache/prepare_summary.json` to match
  `CACHE_FILES` entries and the actual files written by `st00_prepare.py`.
- H.5: `docs/OVERVIEW.md` — preformatted stage table header renamed
  `Script` → `Module`.
- H.6: `README.md` — Python version floor corrected from `3.8+` to `3.6+`
  to match `OVERVIEW.md`, `lib/gitutils.py`, and `lib/validation.py`.
- H.7: `README.md` — output filename corrected from `output/relevant_commits.json`
  to `output/06_relevant_commits.json` (matching `MANIFEST.json` stage 7 outputs).

#### Config/source consistency audit (I)
- I.1: `configs/example-arm-embedded-full.json` — replaced `"project": {"name":…,
  "work_dir":…}` with `"paths": {"work_dir":…}` (canonical per `CONFIGURATION.md`);
  the silently-ignored `project.name` key removed.
- I.2: `configs/example-arm-embedded-full.json` — replaced legacy alias keys
  `use_no_merges` / `use_first_parent` with canonical `no_merges` / `first_parent`.
- I.3: `configs/rules/README` — filter hierarchy rewritten to match actual stage 04
  code: correct L-levels, correct logic labels, added `_filter_reason` / dropped-file
  note.
- I.4: `docs/CONFIGURATION.md` — added `scoring (internal)` section documenting
  `configs/scoring/subsystem_path_hints.json`.
- I.5: `configs/templates/` renamed to `configs/html/`; `MANIFEST.json`
  `template_dir` updated to `configs/html`. `lib/html_report.py` and
  `lib/manifest.py` required no changes (path is manifest-driven).
- I.6: `lib/profile_rules.py` — validation check added: if a profile JSON
  declares a `"name"` field that does not match the filename stem, stage 00
  raises `RuntimeError` immediately.
- I.7: `docs/CONFIGURATION.md` — `history_mapping` section added, documenting
  `mode`, `sample_step`, `max_commits_per_probe`, and `max_failure_rate`.
- I.8: `docs/CONFIGURATION.md` — `collect` section extended with `max_commits`,
  `git_binary`, `use_name_only`, `extra_git_log_args`; all four added as
  commented-out entries in `configs/example-arm-embedded-full.json`.
- I.9: `lib/profile_rules.py` + `lib/stages/st07_report.py` — profile
  `"description"` field is now stored in `profiles_mem` and written to
  `output/profile_summary.json`, making it visible to downstream consumers.

## v9.13.0

### Architecture — Stage runner refactor (E.3)
- All 8 top-level `NN_*.py` stage scripts deleted; pipeline is now run
  exclusively through `kcommit_pipeline.py`.
- Stage logic absorbed: `02_collect_build_context.py` → `lib/stages/st02_build_context.py`,
  `03_build_product_map.py` → `lib/stages/st03_product_map.py`.
- All `lib/stages/*.py` renamed with `stNN_` prefix for unambiguous stage-to-file
  mapping (`st00_prepare.py` … `st07_report.py`).
- `lib/stages/__init__.py` is now the stage registry; exports `STAGES` (ordered list
  of `(key, run_fn)` pairs) and `NSTAGES`. `kcommit_pipeline.py` iterates it directly —
  no subprocess calls, no filename knowledge, no hardcoded stage count.
- `kcommit_pipeline.py` rewrites `cmd_run` as an in-process stage runner using
  `_run_stage()` helper; `cmd_report` calls `st07_report.run()` directly (E.10).

### Cache filenames (E.2)
- `lib/manifest.py` now exports `CACHE_FILES` dict — single source of truth for all
  `NN_*.json` filenames. All stages replaced bare string literals with `CACHE_FILES[key]`.

### Stage count (E.1)
- Hardcoded literal `7` in all `update_stage_progress` / `start_stage` calls replaced
  with `NSTAGES` imported from `lib.stages`.

### Fixes
- D.1: `st01_collect.py` — initial + final progress updates added; trailing newline on stderr.
- D.2: `st04_prefilter.py` — `infer_touched_paths` now imported from `lib.kbuild` (not `lib.scoring`).
- D.3: Stage 03 skips history map when base kbuild map is empty.
- E.4: `st06_postfilter.run()` returns `(relevant, low_score, threshold)`; threshold no
  longer read twice from inconsistent keys.
- E.5: Dead `commit.get('stable_hints')` fallback removed from `lib/scoring.py`.
- E.6: Unused `_load_json_commented` import removed from `lib/scoring.py`.
- E.7: `st04_prefilter.write_outputs()` reads `reports.outputs` (canonical) instead of
  deprecated `templates.*` keys.
- E.9: `lib/profile_rules.py` `schema_hash` now includes all rule file contents, not just
  profile JSON files — stale cache is correctly invalidated on rule changes.
- E.11: `lib/history_map.py` — persistent on-disk `git show` cache under
  `cache/gitshow_cache/`; repeated runs with the same kernel range skip git-show entirely.
- E.12: `st05_score.py` — `precompile_rules()` called once before serial loop, not per-commit.

## v9.12.0

### Improvements

- **Stage renaming** (landed as v9.10.1 patch)
  Stage 4 renamed from `filter_commits` / `04_filter_commits.py` to
  `prefilter_commits` / `04_prefilter_commits.py`.
  Stage 6 renamed from `select_commits` / `06_select_commits.py` to
  `postfilter_commits` / `06_postfilter_commits.py`.
  All references updated in `MANIFEST.json`, `pipeline_state.json` tracking
  calls, `STAGE_OUTPUTS`, and `STAGE_ORDER`.

- **Proposal 4 — lightweight config schema** (`lib/config.py`)
  `CONFIG_SCHEMA` introduced as a plain dict-of-dicts: the single source of
  truth for all config key types. `_PATH_KEYS` is now derived from the schema
  at module load time — no longer a hand-maintained static set.
  Schema drives type validation in `lib/validation.py`, replacing scattered
  manual `isinstance` checks.

- **Proposal 10 — `profiles.active` empty = hard error** (`lib/validation.py`)
  Empty or absent `profiles.active` is now a blocking error (was a notice).
  On Python ≥ 3.11 `_emit_schema_errors()` builds an
  `ExceptionGroup('config schema violations', [...])` for callers that prefer
  structured exception handling via `except*`; on Python 3.6–3.10 the public
  `(problems, notices)` API is unchanged.

- **Topic A — `lib/gitutils.py`: modernised subprocess + latent key bug fix**
  `run_git()` uses `subprocess.run(capture_output=True, text=True)` on
  Python ≥ 3.7; `Popen`+`communicate()` retained as the Python 3.6 fallback
  (detected via `_PY37 = sys.version_info >= (3, 7)` at import time).
  `parse_pretty_block()` replaced the `startswith` chain with
  `str.partition('=')`. Latent bug fixed: `collect.use_no_merges` and
  `use_first_parent` are now accepted as transparent fallbacks for the
  canonical keys `no_merges` / `first_parent`.

- **Topic B — `lib/scoring.py`: dead alias removed**
  `extract_stable_hints = extract_commit_meta` backward-compatibility alias
  deleted.

- **Topic C — `lib/scoring.py`: `_collect_product_evidence()` extracted**
  Product-evidence collection (config map, build log, artifact, config text
  hits) extracted from `score_commit()` into a dedicated
  `_collect_product_evidence(commit, product_map)` function.
  `score_commit()` is now focused on scoring logic only.

- **Topic D — `lib/patterns.py`: `_PRECOMPILED_IDS` id-reuse hazard fixed**
  Module-level `set` of `id()` values removed entirely. `precompile_rules()`
  now sets `profile_rules['__compiled__'] = True` as a sentinel key — eliminates
  the silent skip caused when Python reused a memory address for a dead dict.

- **Topic E — `lib/pipeline_runtime.py`: progress bar routed to stderr**
  `update_stage_progress()` now writes to `sys.stderr` and returns immediately
  when stderr is not a TTY (`_STDERR_IS_TTY` evaluated once at import time).
  `start_stage()`, `finish_stage()`, `fail_stage()`, `print_stage_input()`,
  and `print_stage_output()` all write to stderr via a shared `_eprint()`
  helper. Prevents bar characters from corrupting `--progress-json` stdout
  streams and redirected log files.

- **Topic F — `MANIFEST.json` + `lib/manifest.py`: stage outputs in manifest**
  The `STAGE_OUTPUTS` dict previously hardcoded in `kcommit_pipeline.py` is
  now declared as an `"outputs"` list per stage entry in `MANIFEST.json`.
  `lib/manifest.py` derives `STAGE_OUTPUTS` from the manifest at load time.
  Adding or renaming a stage output now requires a single edit in one file.

- **Topic G — `lib/html_report.py`: `lru_cache` replaces manual cache dict**
  `_TEMPLATE_CACHE = {}` module-level dict removed. `_get_template()` is now
  decorated with `@functools.lru_cache(maxsize=None)` — same performance,
  trivially clearable with `_get_template.cache_clear()`.

- **Topic H — `lib/validation.py` + `lib/config.py`: unused `scoring` section removed**
  The `scoring` top-level config section had no defined keys and no pipeline
  consumer. Its `CONFIG_SCHEMA` entry and the numeric validation loop in
  `_validate_common()` have been removed. A user-authored `"scoring"` key is
  now silently ignored, consistent with other unrecognised top-level sections.

- **Topic I — Python version branching documented**
  Python 3.6 (Ubuntu 18 LTS) remains the minimum supported floor. Improved
  APIs activate automatically: `subprocess.run` with `capture_output` on
  ≥ 3.7; `ExceptionGroup` for structured validation errors on ≥ 3.11.
  Documented in `docs/OVERVIEW.md` under *Runtime requirements*.

## v9.11.0

### New features

- **Profile-driven architecture**: all scoring is now exclusively through
  profiles and rules. The legacy `security`, `performance`, `stable`, and
  `product` fixed categories have been fully removed from the scoring engine,
  config schema, and documentation. Profile names are user-defined; the
  built-in examples (`security_fixes`, `security_features`, `performance`)
  remain as reference configs only.

- **`compile_rules_for_config()` rewrite** (`lib/profile_rules.py`):
  rules are now compiled once per run into a deduplicated on-disk schema
  (`cache/00_compiled_rules.json`) and loaded back via
  `load_profile_rules()`. The new schema is a flat dict keyed by profile
  name with `merged` (union of all rule files) and `rules` (per-rule
  weights) sub-keys.

- **Stage 04 pre-filter** (`lib/stages/prefilter.py`):
  heuristic gating before scoring — path blacklist, author filter, and
  global keyword blacklist — extracted into a dedicated stage module.

- **Stage 06 post-filter** (`lib/stages/postfilter.py`):
  score-threshold gating after scoring, applying `filter.min_score`.
  Low-score commits are tagged and merged into the filtered output for
  traceability.

- **`reports.outputs` list** (`lib/config.py`):
  `reports.outputs` list introduced as the forward-looking replacement for
  the `templates.*` boolean flags. Both are recognised in v9.11; the
  `templates.*` flags are deprecated.

- **`update_stage_progress()` in collect stage** (`lib/stages/collect.py`):
  real-time progress reporting added to the commit collection loop.

- **`compile_rules_for_config()` takes `work_dir`** (`lib/profile_rules.py`):
  `work_dir` positional argument added; `lib/stages/prepare.py` updated
  accordingly.

- **`filter.min_score` added to CONFIG_SCHEMA** (`lib/config.py`):
  `filter.min_score` is now a recognised key; validation no longer emits a
  spurious NOTICE for it.

### Bug fixes

- `profiles.active` empty or absent is now a hard validation error.
- `rules_dirs` and `profiles_dirs` existence is validated before the
  pipeline starts.

## v9.10.0

### New features
- **Cache file prefixes**: every cache file is now prefixed with its producing
  stage number (e.g. `01_commits.json`, `04_filtered_commits.json`).
- **Merged filtered output**: stage 06 appends low-score commits (with reason
  `score_below_threshold`) to `04_filtered_commits.json` so all dropped
  commits — pre-filter and post-filter — share a single file with reasons.
- **HTML autofilter — multiselect**: columns with ≤ 20 distinct values
  (e.g. Author, Profiles, Filter reason) get a `<select multiple>` dropdown
  instead of a free-text input.
- **HTML autofilter — smart operators**: text-input columns now support
  numeric operators (`>N`, `<N`, `>=N`, `<=N`, `=N`, `!N`) and glob
  wildcards (`foo*`, `*bar`, `fo?b`).
- **HTML commit detail panel — inline data**: commit data is embedded directly
  in the HTML at generation time (`window.__KC_COMMITS__`). The panel no
  longer attempts to fetch external `.json` files, making reports fully
  self-contained and working from `file://` URLs.
- **Docs consolidated**: 12 docs files replaced by 4 focused files —
  `OVERVIEW.md`, `CONFIGURATION.md`, `PIPELINE.md`, `PROFILES_AND_RULES.md`.
- **Commit date format**: HTML reports now display `YYYY/mm/dd HH:MM:SS`.
- **XLSX shared strings**: XLSX files now use a proper shared strings table
  (`xl/sharedStrings.xml`) instead of inline strings, fixing corruption in
  LibreOffice Calc.

## v9.9.0

### Bug fixes

- **HTML report header — double 'v' prefix in version string**
  The version was displayed as 'vv9.9.0' because `VERSION` from
  `lib/manifest.py` already contains the leading 'v' and the template
  added a second one. Removed the hardcoded prefix in `lib/html_report.py`.


- **`lib/spreadsheet.py` — XLSX files corrupt / LibreOffice cannot open**
  Three root causes:
  1. `_xl_pkg_rels()` was missing the XML declaration header (`<?xml …?>`),
     producing a malformed relationships file that OOXML parsers rejected.
  2. `_WB_TYPE`, `_WS_TYPE`, and `_ST_TYPE` MIME constants were cut-off
     string literals (missing the trailing `+xml` segment on `_WB_TYPE`).
  3. The bold xf in `_STYLES_XML` was missing the required `applyFont="1"`
     attribute, causing LibreOffice to ignore the style entirely.
  All three fixed; every XML entry now includes `standalone="yes"`.

- **`lib/spreadsheet.py` — ODS files corrupt / LibreOffice cannot open**
  The ODS specification (§3.3) requires the `mimetype` entry to be the
  *first* file in the ZIP archive and to use `ZIP_STORED` (uncompressed).
  Previously it was written with `ZIP_DEFLATED` and not guaranteed to be
  first. Fixed using an explicit `ZipInfo` with `compress_type=ZIP_STORED`.

- **HTML summary — filter widgets overlap normal rows in Profile Summary**
  The Profile Summary table was rendered with `_table()`, which injects a
  `<tr class="kc-filters">` row of `<input>` elements into `<thead>`.
  Since the Profile Summary has no meaningful per-column filtering, the
  inputs served no purpose and caused the sticky thead to overlap data rows.
  Fixed by introducing `_plain_table()` (header row only, no filter inputs)
  used exclusively for the Profile Summary section.

- **HTML summary — filter row in Commits table overlaps body rows on scroll**
  `thead { position: sticky; top: 61px }` made the *entire* `<thead>`
  (both the label row and the filter-input row) sticky, so during vertical
  scroll the filter inputs permanently floated over body rows.
  Fixed by scoping the sticky rule to `thead tr.kc-col-headers` only; the
  filter row now scrolls naturally as part of the table content.

### Breaking changes / removals

- **Legacy per-category score columns removed from all outputs**
  The columns `Security`, `Performance`, `Product`, and `Stable` have been
  removed from every output format. These were sub-scores computed by the
  pre-profile scoring engine and are no longer produced by the pipeline.

  All formats now share the same canonical column layout:

  *Commits sheet / HTML commits table:*
  `Rank | SHA | Subject | Author | Date | Score | Profiles | Product Evidence`

  *Profile Summary sheet:*
  `Profile | Count | Total Score | Avg Score`

  *Profile Matrix sheet:*
  `Rank | SHA | Subject | Profile | Total Score | Profile Score`

  This affects: `lib/spreadsheet.py` (`COMMIT_COLS`, `_commit_row`,
  `write_xlsx`, `write_ods`), `lib/html_report.py` (`_commit_row_html`),
  and the HTML detail panel in `configs/templates/summary.js`.

- **HTML detail panel — scoring breakdown shows profile scores instead of legacy keys**
  `configs/templates/summary.js` `renderCommit()` previously read
  `sc.security`, `sc.performance`, `sc.product`, `sc.stable` from the
  per-commit JSON. These keys no longer exist. The panel now reads
  `sc.profiles` (the per-profile score map) and renders each profile name
  with its score pill.

## v9.8.0

### Bug fixes

- **`04_filter_commits.py` — `NameError: json is not defined`** (`import json` was missing).
  `json.dump(dropped_commits, ...)` at line 459 raised `NameError` at runtime.
  Fixed by adding `import json` to the top-level import block.

- **`lib/logsetup.py` — colored output never applied** `_ColorFormatter.__init__`
  was not called with `fmt` / `datefmt`, so the parent `logging.Formatter` used
  its own defaults and the format string defined in `setup_logging()` was silently
  discarded. Fixed by passing `fmt` and `datefmt` explicitly to the constructor.
  Color is now also gated behind `_use_color()` which respects `NO_COLOR` /
  `FORCE_COLOR` environment variables and `sys.stderr.isatty()`, so redirected
  log files are no longer polluted with ANSI escape sequences.

- **`lib/pipeline_runtime.py` — docstring after code in `print_stage_output()`**
  The `reasons = reasons or {}` guard appeared *before* the function docstring,
  making the docstring a dead string expression. Moved after the docstring.

- **`lib/config.py` — `deep_merge()` defined twice** The second definition
  silently shadowed the first with a slightly different implementation.
  Single canonical definition kept; `deepmerge()` camelCase alias retained.

- **`lib/config.py` — `_resolve_relative_paths()` corrupted non-path strings**
  The function walked every string in the entire config tree and absolutised
  anything containing `/` or starting with `.`, corrupting git revision refs
  (e.g. `"v4.14/foo"`), regex patterns, and URL fragments. Replaced with
  `_resolve_known_paths()` which operates on an explicit allowlist of
  path-typed keys (`source_dir`, `build_dir`, `work_dir`, `*_log`, `*_dir`, etc.).

- **`lib/profile_rules.py` — `cfg['paths']` ignored for profiles/rules dirs**
  `compile_rules_for_config()` recomputed `profile_root` / `rule_root` directly
  from `config_dir`, ignoring `cfg['paths']['profiles_dir']` / `rules_dir` that
  `load_config()` already resolved. A user-configured custom directory was
  silently skipped. Fixed by reading from `cfg['paths']` first.

- **`04_filter_commits.py` — local pattern helpers duplicated `lib.patterns`**
  `_match()`, `_any_matches()`, `_any_file_matches()`, `_all_files_match()` were
  re-implemented locally with outdated substring/fnmatch semantics, diverging
  from the canonical v9.2 whole-word / case-insensitive glob logic in
  `lib.patterns`. All four removed; replaced with imports from `lib.patterns`
  (`match`, `anymatches`, `anyfilematches`, `allfilesmatch`).

- **All stage scripts — `apply_override` imported from `kcommit_pipeline`**
  Stages used a fragile dynamic `importlib` loader or `from kcommit_pipeline
  import apply_override` to obtain the override helper. `lib.config` already
  exports `apply_override` directly. All stages (`00`–`06`) updated to import
  from `lib.config`; the `_import_override()` helper in stage 04 removed.

- **`00_prepare_pipeline.py` — duplicate directory existence check**
  The script manually checked for `profiles/` and `rules/` directories, then
  called `compile_rules_for_config()` which performed the identical checks and
  raised `RuntimeError`. The redundant manual pre-check removed;
  `RuntimeError` from `compile_rules_for_config()` is now caught and routed
  to `fail_stage()`.

- **`kcommit_pipeline.py` — local `_deep_merge()` duplicate**
  A private `_deep_merge()` shadowed the imported `deep_merge` from `lib.config`.
  Removed; all callers use the canonical `lib.config.deep_merge`.

### New features

- **Multiple profiles and rules directories** (`lib/config.py`, `lib/profile_rules.py`,
  `lib/validation.py`, `configs/example-arm-embedded-full.json`):
  The configuration now accepts list forms for the profiles and rules search paths:

  ```json
  "profiles": {
    "active": { "my_profile": 100 },
    "profiles_dirs": ["${CONFIGDIR}/profiles", "/shared/team/profiles"]
  },
  "rules": {
    "rules_dirs": ["${CONFIGDIR}/rules", "/shared/team/rules"]
  }
  ```

  When multiple directories are given, `compile_rules_for_config()` searches all
  of them in order. **Name collisions are an error**: if a profile or rule name
  is found in more than one directory, a `RuntimeError` is raised listing every
  conflicting path. Single-directory `profiles_dir` / `rules_dir` keys remain
  supported as before. Default when neither key is present:
  `${CONFIGDIR}/profiles` and `${CONFIGDIR}/rules`.

  `lib/validation.py` validates every directory in the list and reports
  missing directories as blocking errors. `cfg['paths']` now carries both
  `profiles_dirs` (list) and `rules_dirs` (list) alongside the legacy
  single-dir keys for backward compatibility.

### Removed

- **`lib/stagerunner.py` deleted** — defined `runstage()` but was not called
  by any stage script. Dead code removed.

## v9.7.0

### Bug fixes
- **Colored log output** (`lib/logsetup.py`): `_ColorFormatter` now correctly
  passes `fmt` and `datefmt` into `super().__init__()` so ANSI color codes are
  always emitted. Color is no longer gated behind a TTY check.
- **Column consistency**: all output formats (HTML, CSV, XLSX, ODS) now use the
  same 12-column schema defined by `COMMIT_COLS` in `lib/spreadsheet.py`.
  Filtered-commit CSV adds a `Filter reason` column. Previously HTML had only 5
  columns and filtered CSV had a different ad-hoc 5-column layout.

### New outputs
- `output/filtered_commits.json` — dropped commits written by stage 04 whenever
  any output format is enabled (previously missing entirely).
- `output/profile_matrix.json` — written by stage 06 alongside
  `profile_matrix.csv` (previously missing).

### HTML report (`lib/html_report.py` + `configs/templates/`)
- **High-tech dark theme** (`summary.css`, 411 lines): dark `#0d1117` background,
  neon `#00d4aa` accent, sticky table headers, score pills (green/amber/red),
  profile chips, slide-in commit-detail panel.
- **Section order fixed**: Run Stats → Profile Summary → Commits table.
  Previously commits appeared first.
- **Autofilter** (`summary.js`): per-column live filter inputs below each header
  row; "Clear all" button resets all filters at once.
- **Column sort**: click any column header to sort ascending/descending.
- **SHA commit detail panel**: clicking a SHA opens a slide-in panel that
  fetches `output/<sha12>.json` relative to the HTML file. Shows subject,
  author, date, score breakdown, product evidence and commit body. Falls back
  gracefully when the JSON file is absent. No full-JSON embed in HTML.

## v9.3.0

### Bug fixes

- **Stage 04** — `from lib.pipeline_runtime import (...)` was located inside
  `main()` (indented, lazy import) instead of at module level alongside all
  other lib imports.  Moved to module level so the names are always available
  on import, consistent with stages 01–03, 05–06.

- **Stage 04** — filter result summary was printed twice: once by an explicit
  `print(f'  filter: {total} → …')` + reasons loop, and once by the new
  `print_stage_output()` call added in v9.2.  Removed the redundant manual
  block; `print_stage_output()` is the single source of truth.

### Housekeeping

- `lib/patterns.py` — updated module docstring version tag from "v9.2" to
  "v9.4" to reflect current semantics.

## v9.2.0

### Bug fixes
- `lib/scoring.py`: `_match()` called `fnmatch.fnmatch()` but `fnmatch` was
  never imported — `NameError: name 'fnmatch' is not defined` at runtime.
  Fixed by removing the internal `_match()` / `_compile_pat()` / `precompile_rules()`
  duplicates from `scoring.py` and delegating exclusively to `lib.patterns`.

### Pattern matching — new semantics (v9.2)
- **keyword** (no unescaped glob metacharacters): now matches whole words only
  (`\b` boundaries, case-insensitive).  Previously any substring matched.
  Glob chars can be escaped with `\` to use them as literals (`\*`, `\?`, `\[`).
- **glob** (`*` `?` `[` unescaped): now matched case-insensitively.
  Previously `fnmatch` was case-sensitive on Linux.
- **`re:EXPR`**: case-**sensitive** by default (was case-insensitive before).
  Use `re:(?i)EXPR` to opt into case-insensitive matching.

### Rules files cleanup
- All 5 repeated header comment lines removed from every `*list.txt` file.
- 54 files that were comment-only (no actual patterns) deleted.
- New `configs/rules/README` consolidates all format documentation, including
  the new v9.2 pattern semantics, file naming convention, and filter hierarchy.

### Configuration cleanup
- Removed empty `"scoring": {}` section from example config
  (dead since v8.11 when scoring was made profile-only).

### Per-stage statistics
- Each stage (01–06) now prints to stdout:
  - **Before**: `┌ input [label]: N records` — count of records from previous stage
  - **After**: `└ output [label]: kept=N dropped=M (P% kept) [Xs]` with per-reason
    breakdown for stage 04 (filter) and score distribution for stage 05.

### Removed
- `lib/scoring.py`: internal `_match()`, `_compile_pat()`, `precompile_rules()` —
  all replaced by `lib.patterns` equivalents (single source of truth).

## v9.1.0

### Bug fixes
- `filter.require_kconfig_coverage`: validator now correctly accepts `null` as
  the documented "auto" state (`null`=auto-detect, `true`=force, `false`=disable).
  Previously the strict bool check raised _"must be true or false, got None"_
  whenever the config contained `"require_kconfig_coverage": null` (the default
  in the shipped example config).  The runtime in `04_filter_commits.py` already
  handled `None` correctly; only the validator was wrong.

### Removed
- `filter.require_product_map`: deprecated since v8.11 and removed in v9.1.
  Use `filter.require_kconfig_coverage` instead.  Any config still using this
  key will get an "unrecognised key" notice.

### Improvements
- `lib/validation.py`: extracted `_validate_common()` helper to eliminate ~60
  lines of copy-paste duplication between `validate_inputs()` and
  `validate_config_only()`.
- `lib/validation.py`: updated module docstring to reflect v9.0 and v9.1 changes.
- `lib/stagerunner.py`: removed unused `index` parameter from `runstage()`.
- `lib/__init__.py`: added explicit `__all__` list.
- `lib/html_report.py`: template files now cached at module level instead of
  being re-opened on every `generate_html_report()` call.

# Changelog

## v9.0.0 — 2026-04-30

### Fixed
- `lib/html_report.py`: `_COLS` was undefined at module level causing a
  `NameError` whenever the HTML report was generated.  Defined as a
  module-level constant (6 columns: `#`, `Commit`, `Subject`, `Score`,
  `Flags`, `Profiles`) immediately before `generate_html_report()`.

### Changed
- `MANIFEST.json`: version corrected to `v9.0.0` (was stuck at `v8.9.0`
  since the v8.10 commit cycle); `template_dir` key removed.
- `configs/templates/`: directory deleted — `base.html`, `report_summary.html`,
  `summary.css` were unused since `lib/html_report.py` became self-contained
  in v8.6.
- `05_score_commits.py`: removed dead fallback chain
  (`enriched_commits.json` → `commits.json`); stage 04 always produces
  `filtered_commits.json` so no fallback is needed.
- `lib/scoring.py`: `score_commit()` now auto-calls `precompile_rules()` when
  the caller has not pre-compiled patterns (guards via `_PRECOMPILED_IDS`).
  Stale docstring updated (no more `security_score`/`performance_score` fields).
- `configs/example-arm-embedded-full.json`: `filter.require_kconfig_coverage`
  option added and documented (`null` = auto, `true` = enforce, `false` = off).
- `00_prepare_pipeline.py`: removed duplicate `import json`.

## v8.7.0 — 2026-04-29

### Bug fixes

- **CSV output** (`06_report_commits.py`): removed stale `security_score`,
  `performance_score`, `stable_score`, `product_score` columns (keys absent
  from v8.6+ scoring output). Replaced with `flags` column (comma-separated:
  `cve,fix,stable,perf`) and per-profile score columns (`score_<profile>`).
- **`report_stats.json`**: replaced always-zero `commits_with_security_score`
  etc. with `commits_with_cve`, `commits_with_fix`, `commits_with_stable`,
  `commits_with_perf` derived from `scoring_meta`. Added `filter_stats` block
  from stage 04 pipeline state.
- **`lib/scoring.py`**: safe `touched_paths_guess` access — no longer raises
  `KeyError` when enrichment was skipped (e.g. `--from 5`).
- **Profile summary HTML** (`lib/html_report.py`): stale `<pre>` JSON fallback
  removed; profile summary is always rendered as a styled table sorted by
  total score descending.

### New features

- **Per-profile per-rule weight override** (`lib/profile_rules.py`): rule
  entries in profile JSON now accept a dict form in addition to plain integers:
  ```json
  "rules": {
    "security_general": {
      "weight": 70,
      "keywords_whitelist_extra": ["my_subsystem_vuln"]
    },
    "security_cve_bugs": 100
  }
  ```
  `*_extra` keys (`keywords_whitelist_extra`, `path_whitelist_extra`, etc.) are
  merged with patterns read from the shared rule folder, enabling per-profile
  customisation without duplicating the folder. Plain integer weights unchanged.

- **`--list-stages`** (`kcommit_pipeline.py`): prints stage index, key, script,
  status (pending / running / ok / failed), and duration then exits.
  ```
  python3 kcommit_pipeline.py --config cfg.json --list-stages
  ```

- **`filter` section validation** (`lib/validation.py`): unknown keys in
  `filter` produce a notice; non-boolean values for `enabled`,
  `path_blacklist_global`, `require_product_map` are errors caught at stage 0.

- **Filter KPI card** (`lib/html_report.py`): "Pre-filtered out" and
  "Kept for scoring" KPI cards appear when stage 04 dropped any commits.

- **`load_profile_rules()` recompile warning** (`lib/profile_rules.py`): emits
  `warnings.warn` when `compiled_rules.json` is absent and rules are silently
  recompiled, making `--from 5` misuse visible.

---

## v8.6.0 — 2026-04-29

### Breaking changes

- **Stage 04 renamed**: `enrich_commits` → `filter_commits` (`04_filter_commits.py`).
  Enrichment is now folded into the filter stage. The old `04_enrich_commits.py`
  is removed. External tooling referencing that script must be updated.

- **Scoring model**: `security_score`, `performance_score`, `stable_score`,
  and `product_score` **no longer contribute to the combined score**.
  Score is now the sum of per-profile rule contributions only.
  The `scoring` config section (product/security/performance/stable/symbol_match
  multipliers) is silently ignored — remove those keys from your config.

- **Column removals** in CSV/XLSX/ODS output: `security_score`,
  `performance_score`, `stable_score`, `product_score`, `symbol_match_score`.
  These values are still available in JSON under `commit['scoring']['meta']`.

### New features

- **`--override JSON`** flag on `kcommit_pipeline.py` and all stage scripts:
  deep-merges a JSON object into the loaded config at runtime. Nested keys
  are merged recursively; scalar values and lists are replaced.
  Forwarded automatically to every stage script.
  ```
  --override '{"kernel":{"rev_old":"v4.14.111"}}'
  ```

- **Pre-scoring filter stage (04)** (`04_filter_commits.py`):
  three-rule filter drops structurally irrelevant commits before scoring:
  1. SHA in any profile's `commit_blacklist` (always active).
  2. ALL touched files match the merged `path_blacklist` across active profiles
     (`filter.path_blacklist_global`, default `true`).
  3. No touched file appears in the product map
     (`filter.require_product_map`, default `false`, opt-in).
  Drop statistics and per-reason counts are logged and stored in pipeline state.

- **HTML report redesign**:
  - Analysis date/time in `<title>` and page header subtitle.
  - Dark/light mode toggle with system-preference auto-detection.
  - Satoshi font (Fontshare CDN) for improved typography.
  - Gradient header (teal → dark teal).
  - 4-band score badges: Critical (≥300) / High (≥150) / Medium (≥50) / Low.
  - Inline flag badges per commit: CVE / Fix / Stable / Perf.
  - Card hover shadows and smooth transitions.

- **Example config** (`configs/example-arm-embedded-full.json`):
  all available options documented with inline comments, including the new
  `filter` section and clarifications for the `scoring` section.

### Documentation

- `README.md` fully rewritten for v8.6: pipeline stages, scoring model,
  `--override`, filter stage, config reference, directory layout.
- `docs/ARCHITECTURE.md` updated: filter stage diagram, scoring formula,
  `--override` deep-merge notes, file roles.
- `docs/CONFIGURATION.md` updated: `filter` section added; `scoring` section
  annotated as reserved; `--override` documented; `templates.css_override`
  replaces deprecated `templates.summary_css`.
- `docs/WORKFLOW.md` rewritten: iteration cycles, stage restart guide,
  stage input/output map, CI/CD override pattern, dry-run usage.
- `docs/REPORTS.md` rewritten: output file list, column descriptions,
  v8.6 column removals, HTML report features, customisation via `css_override`.

---

## v8.5.1 — (previous)

Bug-fix release: stable-hint detection false positives, spreadsheet column
alignment, profile matrix edge case with zero-weight profiles.

## v8.5.0 — (previous)

Parallel scoring with worker pool, XLSX/ODS stdlib export, profile matrix CSV,
profile weight multipliers.

## v8.4.0 — (previous)

Global extras scoring (security_score, performance_score, stable_score,
product_score). HTML report with basic CSS. Example ARM config.

- Add miniature test-only pipeline assets under `tests/` (`tests/mini-sample/mini-kernel`, `tests/mini-sample/profiles`, `tests/mini-sample/rules`, and `tests/mini-sample/configs/test-mini.json`) plus `tests/test_full_pipeline_with_mini_inputs.py` for a fuller end-to-end regression.
