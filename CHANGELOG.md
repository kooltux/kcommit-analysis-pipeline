# Changelog

All notable changes to this project will be documented in this file.

## v14.0.0 — prefilter: suppress kw_wl rescue when file evidence is authoritative (2026-06-11)

### Fixed (A — kw_wl rescue suppression)

- `lib/stages/st04_prefilter.py` — the keyword whitelist rescue inside the
  L2½ kconfig-coverage miss path is now **suppressed when `compiled_files` is
  non-empty**.

  **Root cause.** When a commit's files had no kconfig coverage, `filter_decision()`
  checked for keyword whitelist matches and, if found, returned
  `keep, 'keywords_whitelist'` — even when `compiled_files` was fully populated
  and the commit's files were conclusively absent from the product build.  This
  meant that a commit like `b238eaa1` (`btrfs: reschedule when cloning lots of
  extents`) touching only `fs/btrfs/ioctl.c` — with `CONFIG_BTRFS_FS` absent
  from `config_enabled_map` — could be rescued by generic security terms
  (`BUG`, `soft lockup`) in the commit body, keeping it in the final report
  despite the subsystem not being built in the product.

  **Fix.** The kw_wl rescue at L2½ is gated on `compiled_files` being empty:

  ```python
  # BEFORE — rescue always tried when kconfig miss detected
  if kw_wl:
      kw_wl_hits = _collect_hits(kw_wl, [subj, body])
      if kw_wl_hits:
          return 'keep', 'keywords_whitelist', d
  return 'drop', 'no_kconfig_coverage', d

  # AFTER — rescue only when no file-coverage data exists
  if kw_wl and not compiled_sets.get('compiled_files'):
      kw_wl_hits = _collect_hits(kw_wl, [subj, body])
      if kw_wl_hits:
          return 'keep', 'keywords_whitelist', d
  elif kw_wl:
      # compiled_files non-empty: record what would have matched, but suppress
      kw_wl_hits = _collect_hits(kw_wl, [subj, body])
      if kw_wl_hits:
          d = _debug(kw_wl_rescue_suppressed=True)
          d['l1a_kw_wl_matches'] = kw_wl_hits
          return 'drop', 'no_kconfig_coverage', d
  return 'drop', 'no_kconfig_coverage', d
  ```

  **Design contract:**
  - `compiled_files` non-empty → file evidence is authoritative; kw_wl rescue
    suppressed; commit dropped with `no_kconfig_coverage`.
  - `compiled_files` empty (no `.config`, no kconfig evidence) → kw_wl rescue
    still applies; keyword matching is the best available heuristic in that
    situation.

- New debug field `kw_wl_rescue_suppressed` (bool) added to `debug_detail`
  for **all** code paths (default `False`).  Set to `True` only when the
  suppression branch is taken.  `l1a_kw_wl_matches` is also populated in the
  suppressed case, showing which patterns would have matched, for operator
  traceability in `prefilter_debug.json`.

- Module docstring and `filter_decision()` docstring updated to document the
  kw_wl rescue rule and the `kw_wl_rescue_suppressed` debug field.

### Tests (A)

- `tests/test_prefilter.py` — added 6 new regression tests:

  | Test | Assertion |
  |---|---|
  | `test_kw_wl_rescue_suppressed_when_compiled_files_nonempty` | Commit touching uncovered files dropped even when kw_wl matches (compiled_files non-empty) |
  | `test_kw_wl_rescue_suppressed_debug_shows_matching_patterns` | `kw_wl_rescue_suppressed=True` and `l1a_kw_wl_matches` populated when suppressed |
  | `test_kw_wl_rescue_allowed_when_compiled_files_empty` | Rescue still keeps commit when `compiled_files` is empty |
  | `test_kw_wl_rescue_suppressed_btrfs_real_world_scenario` | End-to-end: `b238eaa1` btrfs commit dropped after fix |
  | `test_debug_detail_has_kw_wl_rescue_suppressed_key` | `kw_wl_rescue_suppressed` present in debug_detail for all paths |
  | `test_kw_wl_rescue_suppressed_false_by_default` | Field is `False` on normal keep/drop paths |

- `test_debug_detail_is_dict_with_required_keys` updated to assert
  `kw_wl_rescue_suppressed` is present in the required keys set.

- `test_debug_kconfig_uncovered_populated_when_kw_wl_saves_commit` updated
  to use `compiled_files=set()` (empty) to reflect that the rescue is only
  exercised when no file-coverage data exists, and to assert
  `kw_wl_rescue_suppressed=False` on the kept path.

### Documentation (A)

- `docs/PIPELINE.md` — Stage 04 description updated with the kw_wl rescue
  suppression rule and the `kw_wl_rescue_suppressed` debug field; `## v14.0.0
  changes` section added.

### Version

- `MANIFEST.json` version bumped from `v13.0.3` → `v14.0.0`.

---

## v13.0.1 — prefilter: Bug-1 disabled-symbol false-keep fix (2026-06-10)

### Fixed (Bug-1 / H)

- `lib/stages/st03_product_map.py` — added `_filter_to_enabled()` and
  `config_enabled_map` / `config_enabled_dirs` fields to the product map.

  **Root cause.** `config_to_paths` contains every CONFIG symbol found in
  Makefile/Kbuild files across the entire source tree, regardless of whether
  that symbol is enabled in the product `.config`.  Previously,
  `st04.build_compiled_sets()` and `st05._collect_product_evidence()` read
  directly from `config_to_paths`, so disabled symbols (e.g. `CONFIG_BTRFS_FS`
  on an SDX55 product) were treated as compiled, and commits touching those
  paths were incorrectly kept with `build_artifact` or `config_map` evidence.

  **Fix.** `_filter_to_enabled(config_map, raw_config_lines)` intersects
  `config_to_paths` with symbols that have `=y` or `=m` in `.config`,
  producing `config_enabled_map`.  `config_enabled_dirs` is derived from
  that filtered map.  Both fields are written into `product_map.json` at
  stage 03 so all downstream stages share one consistent, pre-filtered view.

- `lib/stages/st04_prefilter.py` — `build_compiled_sets()` now reads
  `config_enabled_map` and `config_enabled_dirs` from `product_map` instead
  of computing them at runtime from `config_to_paths` + `enabled_configs`.
  Returns `available=False` (with a warning) when `config_enabled_map` is
  absent so that running st04 against a pre-v13.0.1 cache is detected early.

- `lib/scoring.py` — `_collect_product_evidence()` now reads
  `config_enabled_map` for `config_map:CONFIG_X` evidence tags instead of
  `config_to_paths`, preventing disabled symbols from generating evidence.

### Tests (H)

- `tests/test_st03_product_map.py`
  - Added 8 unit tests for `_filter_to_enabled()`: covers `=y`, `=m`, `=n`,
    string values, bare symbols, empty inputs, path preservation, and
    symbol-not-in-map.
  - `test_run_writes_product_map`: asserts `config_enabled_map` and
    `config_enabled_dirs` keys present in written JSON.
  - `test_run_config_enabled_dirs_derived`: `fs/btrfs/` absent from
    `config_enabled_dirs` when `CONFIG_BTRFS` is not in `.config`.
  - `test_run_disabled_symbol_excluded_from_enabled_map`: primary Bug-1
    regression test — `CONFIG_BTRFS_FS` present in `config_to_paths` but
    absent from `config_enabled_map` when not in `.config`.
  - `test_run_config_enabled_map_empty_when_no_kbuild_data` /
    `_empty_when_no_enabled_configs`: edge-case coverage.
  - **Test infra fix** (`_build_context`): replaced `field or default` with
    `field if field is not None else default` for `kernel_config`,
    `build_log`, and `artifacts` so that an explicit `[]` is preserved
    (falsy `[]` was silently replaced by the default, masking the
    no-enabled-configs test scenario).
  - **Test infra fix** (`_setup`): explicitly removes any stale
    `kbuild_map.json` from the cache dir when `kbuild_map=None` is passed,
    preventing tmp_path name-collision from leaving a false pre-existing map
    and sending `run()` into the wrong branch.

- `tests/test_prefilter.py`
  - `test_build_compiled_sets_missing_enabled_map_returns_empty`: pre-v13.0.1
    cache (no `config_enabled_map`) returns `available=False`.
  - `test_build_compiled_sets_disabled_symbol_absent`: `config_enabled_map`
    without BTRFS → no btrfs paths in `compiled_files` / `compiled_dirs`.
  - `test_btrfs_commit_dropped_by_kconfig_when_disabled`: end-to-end Bug-1
    regression — BTRFS commit dropped with `no_kconfig_coverage` when
    `CONFIG_BTRFS_FS` is absent from `config_enabled_map`.
  - All `build_compiled_sets()` tests updated to supply `config_enabled_map`
    and `config_enabled_dirs` instead of `config_to_paths` / `enabled_configs`.

- `tests/test_scoring.py` / `tests/test_scoring_extra.py`
  - `_pm()` helper updated to include `config_enabled_map` and
    `config_enabled_dirs` by default.
  - `test_evidence_config_map_hit`: passes `config_enabled_map` to verify
    evidence tag emission.
  - `test_score_commit_product_evidence_config_map`: updated to supply
    `config_enabled_map` in the product map.

### Version

- `MANIFEST.json` version bumped from `v13.0.0` → `v13.0.1`.

---

## v13.0.0 — legacy cleanup, doc accuracy, prefilter reason fix (2026-06-07)

### Fixed (G)

- `lib/stages/st04_prefilter.py` — zero-file commits (merge commits, tag
  objects) now return the keep reason `'no_files_layer'` instead of the
  incorrect `'default'`.

  **Root cause.** The module docstring, the `filter_decision()` docstring, and
  the E.1.5 changelog note in the module header all stated that zero-file
  commits should use the distinct reason `'no_files_layer'` so they can be
  identified separately from commits with files that reach L0 default keep.
  The code, however, still returned `'default'` at that branch, making the
  documentation and the implementation inconsistent.

  **Fix.**
  ```python
  # BEFORE
  return 'keep', 'default', d

  # AFTER
  return 'keep', 'no_files_layer', d
  ```
  The `filter_decision()` docstring was also updated to reference the correct
  reason string and to note that this aligns with the G fix.

### Tests (G)

- `tests/test_prefilter.py` — any existing test asserting `reason == 'default'`
  for a zero-file commit must now assert `reason == 'no_files_layer'`.
  Tests that exercise commits *with* files reaching L0 still assert `'default'`.

### Legacy cleanup (F)

- `docs/OVERVIEW.md` — removed three dangling v10.2.0 changelog bullets from
  the bottom of the file; these already appeared in `CHANGELOG.md`.
- `docs/PIPELINE.md` — removed the four stale embedded changelog sections
  (`## v12.0.2 changes`, `## v12.0.1 changes`, `## v11.4.0 report changes`,
  `## v11.3.2 changes`); all are fully covered in `CHANGELOG.md`.

### Documentation accuracy (H, I, J, K)

- `README.md` (H):
  - `## Cache contract` updated to include `prefilter_debug.json` (stage 04)
    and `postfilter_debug.json` (stage 06).
  - `## Outputs` table: removed the stale `output/rule_trace.json` row
    (that file was removed in v12.0.3).
  - `## Validation` section: replaced the hardcoded stale test-count baseline
    with a pointer to `CHANGELOG.md` and the `pytest` invocation.

- `docs/CONFIGURATION.md` (I):
  - `## Cache files` section replaced with the canonical inventory of all
    13 cache files, using their actual `cache/` filenames.
  - `### scoring (internal)` paragraph: removed the confusing reference to
    `reports.css_override` as a way to override scoring hints; there is no
    such user-facing key.

- `docs/OVERVIEW.md` (J):
  - Pipeline table: stage 04 now shows `prefilter_kept_commits.json`,
    `filtered_commits.json`, and `prefilter_debug.json` as outputs.
  - Pipeline table: stage 05 input corrected from `filtered_commits.json`
    to `prefilter_kept_commits.json`.
  - Pipeline table: stage 06 now shows `postfilter_dropped_commits.json`
    and `postfilter_debug.json` as outputs.
  - Drop-list paragraph updated to describe the two separate stage 04 / 06
    drop files and how stage 07 merges them.

- `docs/PIPELINE.md` (K):
  - Stage 06 description updated to document `postfilter_debug.json` as a
    new output (added in E.7).
  - Stage 04 description updated to note the `no_files_layer` reason and
    `prefilter_debug.json` output.
  - Added `## v13.0.0 changes` section summarising all E.* and G fixes.

### Version

- `MANIFEST.json` version bumped from `v12.0.3` → `v13.0.0`.

---

## v12.0.2 — prefilter: directory-scoped log-basename artifact evidence (2026-06-03)

### Fixed (C)

- `lib/stages/st04_prefilter.py` — `_file_has_artifact()` now scopes
  **log-derived basename matches** (`log_basenames`) to the file's parent
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

  **Fix.** A log-basename hit is accepted only when the file's parent
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
  caused stage 04's L2½ `build_artifact` check to keep commits that should
  have been eliminated by the prefilter — resulting in insufficient commit
  reduction when a real build tree was provided.
- The set of excluded names is defined in the new constant
  `_KBUILD_PLACEHOLDER_NAMES` (currently `{'built-in.o', 'built-in.a'}`) so
  it can be extended and independently tested.

### Tests (A.2, A.3)
- `tests/test_st02_build_context.py` — added 6 regression tests.
- `tests/test_prefilter.py` — added 4 regression tests.

### Documentation (A.4)
- `docs/PIPELINE.md` — Stage 02 bullet updated to explain placeholder exclusion;
  v12.0.1 changes section added.

### Version
- `MANIFEST.json` version bumped from `v12.0.0` → `v12.0.1`.

---

## v12.0.0 — stage-7 progress fix + evaluation sidebar (2026-06-02)

### Fixed (A.3)
- `lib/stages/st07_report.py` — `_update_stage7_progress()` corrected.

### Added (A.4)
- `_build_evaluation_block()` helper; evaluation sidebar in HTML report.

### Version
- `MANIFEST.json` version bumped from `v11.3.2` → `v12.0.0`.

---

## v11.3.2 — report fixes, tests, and measured coverage (2026-05-12)

- HTML report sidecar flow refined; main table no longer shows Product Evidence column.
- Measured test baseline: **465 tests passing**, **85%** total `lib/` coverage.

## v11.3.1 - 2026-05-11

- HTML report theme toggle button Firefox fix.

## v11.3.0 - 2026-05-11

- Switched HTML table filtering to precomputed per-row data arrays.

## v11.2.x - 2026-05-09 to 2026-05-11

- Firefox compatibility, loading animation, theme toggle, detail pane, CSV export, filter counter, built-in alias fallback, singular path alias, profile/rule fallback/override.

## v10.x - 2026-05-09

- v10 pipeline contract cleanup: split cache files, strict config validation, schema validation.

## v9.14.17 — 2026-05-09

- Filtered-commit output in all report formats.
