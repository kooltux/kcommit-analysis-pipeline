# Changelog

All notable changes to this project will be documented in this file.

## v16.0.0 — prefilter: Kconfig/Makefile directory-scoped coverage (2026-06-13)

### Fixed (C — build-system file coverage scoping)

- `lib/stages/st04_prefilter.py` — `_file_is_kconfig_covered()`: build-system
  files (`Kconfig`, `Makefile`, `Kbuild`, `*.mk`) no longer receive an
  unconditional coverage pass.

  **Root cause.**  `_file_is_kconfig_covered()` called `_is_build_system_file(f)`
  as its final fallback, which returned `True` for any file named `Kconfig`,
  `Makefile`, `Kbuild`, or matching `Kconfig.*` / `Makefile.*` / `*.mk` —
  regardless of its location in the kernel tree.  This caused a false-keep for
  commits that touched only build-system files in subsystems that were not
  compiled into the product.  Example: a commit modifying `fs/btrfs/Kconfig`
  was kept even when `CONFIG_BTRFS_FS` was absent from `config_enabled_map`,
  because the file name alone triggered the build-system pass.

  **Fix.**  A build-system file is now considered covered only when:

  1. The file itself appears in `compiled_files` (exact match), OR
  2. The file's parent directory — normalised to the trailing-slash form stored
     by `st03 _derive_config_dirs()` — is present in `compiled_dirs`, OR
  3. The file is at the kernel root (`os.path.dirname(f) == ''`).  Top-level
     `Kconfig`, `Makefile`, and `Kbuild` are unconditionally product-relevant.

  The root exception preserves correct behaviour for the kernel's entry-point
  build files while correctly scoping all subsystem-level build files to their
  compiled directories.

  **Trailing-slash normalisation.**  `compiled_dirs` stores entries in the
  trailing-slash form produced by `st03._derive_config_dirs()` (e.g.
  `"drivers/usb/core/"`), while `os.path.dirname()` returns paths without a
  trailing slash.  The lookup now normalises `fdir` to `fdir + "/"` before
  testing membership, making the directory check reliable for all file types
  (previously the check could silently fail for any file when the entry in
  `compiled_dirs` had a trailing slash).

  **Impact summary:**

  | Commit touches | Before | After |
  |---|---|---|
  | `fs/btrfs/Kconfig` only, btrfs not built | **KEPT** (false-keep) | **DROPPED** (`no_kconfig_coverage`) |
  | `fs/btrfs/Makefile` only, btrfs not built | **KEPT** (false-keep) | **DROPPED** (`no_kconfig_coverage`) |
  | `drivers/usb/Kconfig`, USB compiled | KEPT | KEPT (dir in compiled_dirs) |
  | `Kconfig` at kernel root | KEPT | KEPT (root exception) |
  | `Makefile` at kernel root | KEPT | KEPT (root exception) |
  | `fs/btrfs/Kconfig` + `drivers/usb/hub.c` (USB built) | KEPT | KEPT (artifact evidence) |

### Tests (C)

- `tests/test_prefilter.py` — 13 new tests in the `v16.0.0 (C)` section:

  | Test | Assertion |
  |---|---|
  | `test_is_build_system_file_kconfig` | Kconfig variants recognised |
  | `test_is_build_system_file_makefile` | Makefile variants recognised |
  | `test_is_build_system_file_kbuild` | Kbuild recognised |
  | `test_is_build_system_file_mk_extension` | *.mk recognised |
  | `test_is_build_system_file_regular_c_file` | .c files not recognised |
  | `test_file_is_kconfig_covered_kconfig_in_compiled_dir` | Kconfig in compiled dir → covered |
  | `test_file_is_kconfig_covered_kconfig_not_in_compiled_dir` | Kconfig in uncovered dir → not covered |
  | `test_file_is_kconfig_covered_root_kconfig_always_covered` | Root Kconfig → always covered |
  | `test_file_is_kconfig_covered_root_makefile_always_covered` | Root Makefile → always covered |
  | `test_file_is_kconfig_covered_makefile_in_uncovered_dir` | Makefile in uncovered dir → not covered |
  | `test_kconfig_file_in_uncovered_dir_drops` | filter_decision drops btrfs/Kconfig |
  | `test_kconfig_file_in_compiled_dir_keeps` | filter_decision keeps usb/Kconfig |
  | `test_makefile_in_uncovered_dir_drops` | filter_decision drops btrfs/Makefile |
  | `test_root_kconfig_always_keeps` | filter_decision keeps root Kconfig |
  | `test_root_makefile_always_keeps` | filter_decision keeps root Makefile |
  | `test_kconfig_uncovered_plus_covered_source_keeps_via_artifact` | mixed commit kept via artifact |
  | `test_compiled_dirs_trailing_slash_normalisation` | trailing-slash dir lookup works |
  | `test_kconfig_dot_suffix_in_uncovered_dir_drops` | Kconfig.nfs drops |
  | `test_mk_file_in_uncovered_dir_drops` | build.mk drops |
  | `test_auto_require_drops_kconfig_in_uncovered_dir` | auto-require path also drops |

  `_file_is_kconfig_covered` and `_is_build_system_file` added to the import
  list in the test module.

  `_usb_cs()` helper added to reduce compiled_sets fixture boilerplate.

### Documentation (C)

- `docs/PIPELINE.md` — Stage 04 section updated:
  - `_file_is_kconfig_covered()` behaviour documented with the three coverage
    rules and the root exception.
  - Trailing-slash normalisation note added.
  - `v16.0.0 changes` section added.

### Version

- `MANIFEST.json` version bumped `v14.1.0` → `v16.0.0`.

---

## v14.1.0 — prefilter: remove keyword and path-whitelist coupling (2026-06-11)

### Changed (B — keyword/path-wl decoupling)

- `lib/stages/st04_prefilter.py` — removed keyword whitelist/blacklist and
  path whitelist from the prefilter entirely.

  **Design rationale.**  The prefilter answers exactly one question: *is this
  commit built in the product?*  Keywords describe importance or severity; they
  say nothing about whether a commit's files are compiled into the product.
  These are orthogonal concerns and must not be mixed.

  Previously, `build_merged_lists()` pulled `keywords_whitelist`,
  `keywords_blacklist`, and `path_whitelist` directly from the compiled
  scoring profile rules and used them to make binary keep/drop decisions in
  `filter_decision()`.  This created a hidden coupling: any pattern written by
  a profile author to raise a commit's score (e.g. `'BUG'`, `'CVE-'`,
  `'use-after-free'`) simultaneously acted as a stage-04 rescue signal for
  commits that had a kconfig coverage miss — regardless of whether those
  commits were actually built in the product.

  The v14.0.0 partial fix (suppressing the rescue when `compiled_files` was
  non-empty) reduced the false-keep rate but left the fundamental coupling
  intact.  This release removes it completely.

  **Changes:**
  - `build_merged_lists()` deleted.
  - `filter_decision(commit, lists, compiled_sets, filter_cfg, kconfig_enabled)`
    simplified to `filter_decision(commit, compiled_sets, filter_cfg, kconfig_enabled)`
    — the `lists` parameter is gone.
  - L2b (path whitelist), L1a (keyword whitelist), L1b (keyword blacklist)
    layers removed from the filter hierarchy.
  - The kw_wl rescue mechanism at L2½ and the `kw_wl_rescue_suppressed` debug
    field removed.
  - `l2b_path_wl_matches`, `l1a_kw_wl_matches`, `l1b_kw_bl_matches` removed
    from `debug_detail`.
  - SHA whitelist/blacklist (L3) and path blacklist (L2a) retained as explicit
    operator escape hatches.
  - Zero-file commits always get reason `'no_files_layer'`; keyword-based
    zero-file keep/drop removed.
  - `run()` simplified: `load_profile_rules()`, `precompile_rules()`, and
    `build_merged_lists()` calls removed; pattern_counts summary reduced to
    `commit_wl`, `commit_bl`, `path_bl`.
  - Module docstring, `filter_decision()` docstring, and `prefilter_debug.json`
    schema updated.

  **Filter hierarchy after v14.1.0:**
  ```
  L3  SHA whitelist        -> FORCE-KEEP
  L3  SHA blacklist        -> FORCE-DROP
  L2a path_blacklist ALL   -> DROP
  L2half build artifact    -> KEEP
  L2half kconfig miss      -> DROP  (no rescue of any kind)
  L0  default              -> KEEP
  ```

  **Supersedes v14.0.0** kw_wl rescue suppression (that partial fix is no
  longer needed and has been removed along with its debug field).

### Tests (B)

- `tests/test_prefilter.py` — removed all tests for deleted functionality:
  `build_merged_lists` dedup/multiple-profiles tests, L2b path_whitelist keeps,
  L1a/L1b keyword keep/drop, zero-file keyword layers, kw_wl rescue suppression
  tests (all 6 from v14.0.0), `kw_wl_rescue_suppressed` debug key assertions.

  All `filter_decision()` calls updated to the new 4-argument signature.

  Replaced with 3 new tests that document the v14.1.0 invariants:

  | Test | Assertion |
  |---|---|
  | `test_path_whitelist_in_filter_cfg_is_ignored` | path_whitelist in filter config has no effect on prefilter |
  | `test_keyword_in_subject_does_not_rescue_kconfig_miss` | keywords in commit subject/body never rescue a kconfig miss |
  | `test_keyword_in_subject_does_not_keep_path_blacklisted_commit` | keywords never rescue a fully path-blacklisted commit |

  `test_btrfs_kw_match_no_longer_rescues_kconfig_miss` replaces the v14.0.0
  `test_kw_wl_rescue_suppressed_btrfs_real_world_scenario` — commit b238eaa1
  now dropped unconditionally (no rescue mechanism at all).

  `test_debug_detail_is_dict_with_required_keys` updated to the new key set.
  `test_debug_detail_no_kw_or_pathwl_keys` added to assert removed keys are
  absent.

### Documentation (B)

- `docs/PIPELINE.md` — Stage 04 filter hierarchy updated; `v14.1.0 changes`
  section added.

### Version

- `MANIFEST.json` version bumped `v14.0.1` → `v14.1.0`.

---

## v14.0.1 — diagnose: remove cache_presence from JSON output (2026-06-11)

### Changed

- `lib/commands/cmd_diagnose.py` — removed `cache_presence` from the JSON
  output of `diagnose_commit()` and the `cmd_diagnose` CLI.

  `cache_presence` was an inventory of every known cache file with `exists`
  and `size_bytes` fields.  It was redundant: missing files are already
  reported via the `warnings` list, and file sizes carry no diagnostic value
  for understanding why a commit was filtered or scored in a particular way.
  Removing it keeps the output focused on commit-level decision data.

  The `_presence()` helper function has been deleted along with its call-site
  in `diagnose_commit()`.

  Top-level output keys are now:
  `meta`, `commit`, `kernel_annotations`, `pipeline_stages`, `final`, `warnings`.

- `tests/test_cmd_diagnose.py` — removed the three `cache_presence` tests
  (`test_cache_presence_all_keys`, `test_cache_presence_missing_file`,
  `test_cache_presence_existing_file`) and replaced them with a single
  `test_no_cache_presence_in_output` assertion that the key is absent.
  Module docstring coverage list updated accordingly.

- `docs/PIPELINE.md` — module-level output-key list updated; `v14.0.1`
  changes section added.

---

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

  **Superseded by v14.1.0** which removes the rescue mechanism entirely.

### Version

- `MANIFEST.json` version bumped from `v13.0.3` → `v14.0.0`.

---

## v13.0.1 — prefilter: Bug-1 disabled-symbol false-keep fix (2026-06-10)

### Fixed (Bug-1 / H)

- `lib/stages/st03_product_map.py` — added `_filter_to_enabled()` and
  `config_enabled_map` / `config_enabled_dirs` fields to the product map.

- `lib/stages/st04_prefilter.py` — `build_compiled_sets()` now reads
  `config_enabled_map` and `config_enabled_dirs` from `product_map`.

- `lib/scoring.py` — `_collect_product_evidence()` now reads
  `config_enabled_map` for `config_map:CONFIG_X` evidence tags.

### Version

- `MANIFEST.json` version bumped from `v13.0.0` → `v13.0.1`.

---

## v13.0.0 — legacy cleanup, doc accuracy, prefilter reason fix (2026-06-07)

### Fixed (G)

- Zero-file commits now return keep reason `'no_files_layer'` instead of `'default'`.

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
