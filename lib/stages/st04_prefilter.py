"""Stage 04 logic: enrich and pre-filter commits before scoring.

Filter hierarchy (higher level wins):
  L3 SHA whitelist  -> FORCE-KEEP
  L3 SHA blacklist  -> FORCE-DROP
  L2a path_blacklist ALL files -> DROP
        Note: a commit whose files are a *mix* of blacklisted and non-blacklisted
        paths is NOT dropped at L2a; it falls through to L2half and below.  The
        rationale is that a path blacklist entry means "this subsystem is not
        relevant", not "any commit that merely touches this subsystem is junk".
        Only commits where every file lives under a blacklisted prefix are dropped.
  L2half file-type-aware evidence evaluation -> KEEP or DROP
        Each file is classified by type and evaluated accordingly:

        File type       | Evaluation rule
        ----------------+---------------------------------------------------------
        source          | .c .S .cc .cpp .cxx .c++
          artifact hit  |   -> KEEP (build_artifact)
          no hit,       |
           real arts    |   -> DROP vote (not in product build)
          no hit,       |
           no real arts |   -> kconfig coverage check (require active)
          no hit,       |      covered -> KEEP (kconfig_coverage)
           no real arts |      uncovered -> DROP vote
        header          | .h .hpp .hxx .h++
          (any context) |   -> kconfig coverage check (require active)
                        |      covered -> KEEP (kconfig_coverage)
                        |      uncovered -> DROP vote
                        |   always use kconfig regardless of artifact availability
        build-meta      | Kconfig, Makefile, Kbuild, Makefile.*, Kconfig.*, *.mk
          dir covered   |   -> KEEP (kconfig_coverage)
          dir not covd, |
           real arts &&  |
           dir-prefix   |
           art match    |   -> KEEP (build_artifact)  [path-prefix fallback]
          dir not covd, |
           require active|   -> DROP vote
          root-level    |   -> always KEEP (kconfig_coverage)
        dts/dtsi        | .dts .dtsi
          dtb hit       |   -> KEEP (build_artifact)
          no hit,       |
           dtb evidence |   -> DROP vote (DTS file for a board not built)
          no dtb evid.  |   -> neutral (falls to L0 default keep)
        other           | docs, txt, MAINTAINERS, …
          (any context) |   neutral — never vote DROP; falls to L0 keep

        Decision after per-file voting:
          any keep_via_artifact  -> KEEP (build_artifact)
          any keep_via_kconfig   -> KEEP (kconfig_coverage)
          any vote_drop          -> DROP (no_kconfig_coverage)
          all neutral            -> fall through to L0

        The filter is inactive (available=False) when compiled_files is empty
        and no artifacts/log evidence is present; every commit is kept for
        scoring to resolve.

  L0  default                    -> KEEP

Zero-file commits (merge commits, tag objects):
  A commit with no files bypasses all path/artifact/kconfig layers and
  is kept unconditionally with reason='no_files_layer'.

Design contract (v14.1.0 / v16.1.0):
  The prefilter answers exactly one question: is this commit built in the
  product?  Keywords are irrelevant to that question -- they describe
  importance/severity, not build membership.  All keyword and path-whitelist
  matching belongs exclusively in the stage-05 scoring engine.

  path_blacklist is kept as an operator escape hatch for paths that are
  structurally never relevant regardless of build evidence (e.g.
  Documentation/, tools/testing/).  SHA overrides are kept for explicit
  per-commit operator decisions.

  File-type classification (v16.1.0 / v16.4.0):
    The prefilter uses file type to determine WHICH evidence source is
    authoritative for each file in a commit:
    - source files: build artifacts are authoritative; kconfig coverage is
      only used when no real artifact evidence exists at all.
    - header files: kconfig coverage is always authoritative (headers never
      produce build artifacts directly).
    - build-meta files: kconfig coverage first; path-prefix artifact coverage
      as fallback when real artifacts are present.
    - dts/dtsi files: DTB artifact stems are authoritative (v16.4.0 J).
      When DTB evidence is present, only a direct DTB stem hit keeps the file;
      a DTS file whose board DTB was not built votes DROP.  When no DTB
      evidence exists at all, DTS files are neutral (fall to L0 default keep).
    - other files: always neutral; never cause a DROP.

v12.0.0 (A.1) -- filter_decision() returns a 3-tuple
  (action, reason, debug_detail) where debug_detail is a dict keyed by:
    sha, files, filter_enabled, kconfig_required,
    l3_commit_wl_match, l3_commit_bl_match,
    l2a_path_bl_matches,
    l2half_artifact_files,
    l2half_kconfig_covered_files, l2half_kconfig_uncovered_files
  All commits carry this field as 'prefilter_debug' in their sidecar JSON
  (output/commits/*/*/<sha>.json).
  Dropped commits are also aggregated in prefilter_debug.json (cache dir).

v13.0.0 changes (E.1.1-E.1.6, E.6):
  E.1.1 -- _file_has_artifact() called only once per commit in filter_decision();
           result reused for both the guard condition and debug capture.
  E.1.2 -- kconfig_covered/uncovered populated in debug unconditionally.
  E.1.4 -- L2a semantics documented: only drops when ALL files are blacklisted.
  E.1.5 -- zero-file commits get explicit early handling.
  E.1.6 -- build_compiled_sets(): removed ambiguous else-branch that added raw
           'CONFIG_FOO=m' strings (with '=') to enabled_set when the entry had no
           '=' separator.
  E.6   -- removed dead 'tmpl = reports' assignment and stale comment in
           write_outputs().
  G     -- filter_decision(): zero-file default keep now emits reason='no_files_layer'.

v13.0.1 changes (Bug-1 fix):
  H     -- build_compiled_sets(): reads product_map['config_enabled_map'] and
           product_map['config_enabled_dirs'] instead of 'config_to_paths'.

v13.0.2 changes (Bug-2 fix):
  I     -- build_compiled_sets(): available=True when ANY evidence source is
           non-empty (config_enabled_map, built_artifacts_from_dir, or
           built_objects_from_log).

v14.0.0 changes (A -- kw_wl rescue suppression):
  Partial fix: suppressed kw_wl rescue when compiled_files was non-empty.
  Superseded by v14.1.0.

v14.1.0 changes (B -- keyword/path-wl decoupling):
  B     -- Removed keyword whitelist/blacklist and path whitelist from the
           prefilter entirely.  These are scoring concepts, not filter concepts.
           build_merged_lists() deleted.  filter_decision() no longer accepts
           a `lists` argument.  L2b (path_whitelist), L1a (kw_wl), L1b (kw_bl)
           layers and the kw_wl rescue mechanism (including
           kw_wl_rescue_suppressed debug field) are all removed.
           The filter now answers only: "is this commit built in the product?"
           Scoring resolves importance/severity via profile rules.

v16.0.0 changes (C -- Kconfig/Makefile directory-scoped coverage):
  C     -- _file_is_kconfig_covered(): build-system files (Kconfig, Makefile,
           Kbuild, *.mk) no longer receive an unconditional coverage pass.
           A build-system file is now considered covered only when its own
           directory is present in compiled_dirs (i.e. the subsystem it
           configures is built into the product), or when the file lives at
           the kernel root (fdir == '', e.g. the top-level Makefile/Kconfig).

v16.0.1 changes (D -- artifact trailing-slash normalisation):
  D     -- _file_has_artifact(): applied the same trailing-slash normalisation
           to the compiled_dirs membership check that was applied to
           _file_is_kconfig_covered() in v16.0.0.

v16.1.0 changes (F -- file-type-aware L2half):
  F     -- filter_decision(): L2half replaced with a per-file type-aware voting
           loop.  New helpers: _file_is_header(), _file_is_source(),
           _dir_has_artifact_coverage(), _has_real_artifact_evidence().

           Key behavioural changes vs v16.0.1:

           1. Header-only commits: headers are always evaluated against
              kconfig coverage regardless of artifact availability.
              Previously, a header commit in a compiled dir was kept only
              if _file_has_artifact() fired (which it never does for .h
              files since they produce no .o).  Now headers are always
              evaluated via _file_is_kconfig_covered(), consistent with the
              fact that header files are always built as part of compilation.

           2. Kconfig/Makefile path-prefix fallback: when real artifact
              evidence is present (artifact_stems or log_basenames non-empty)
              and a build-meta file's directory is NOT in compiled_dirs
              but IS a prefix of a compiled artifact path, the file is
              kept via build_artifact.  This handles the common case where
              a Kconfig/Makefile sits one level above the compiled subdir
              (e.g. drivers/usb/Kconfig when drivers/usb/core/ is compiled).

           3. New debug field: l2half_has_real_artifacts (bool) -- signals
              whether artifact_stems / log_basenames were non-empty, making
              it easy to distinguish config-map-only runs from full-artifact
              runs in prefilter_debug.

           4. New keep reason: 'kconfig_coverage' -- emitted when a commit
              is kept via kconfig/directory coverage rather than a direct
              artifact hit.  Replaces the implicit 'default' reason that
              was previously emitted for header/build-meta keeps.

vG changes (graceful degradation -- no build artifacts):
  G2    -- run(): renamed c['touched_paths_guess'] to c['_touched_paths_guess'].
           The field is still populated by infer_touched_paths() for debugging
           purposes but is now a private field (underscore prefix) that is
           excluded from JSON output ordering in order_commit_details() and
           from product evidence collection in _collect_product_evidence().
           This decouples the enrichment heuristic from the evidence pipeline
           and prevents misleading evidence tags when build context is partial
           or absent.

v16.3.0 changes (H.2 -- full-path stems for build-log objects):
  H.2   -- build_compiled_sets(): built_objects_from_log entries are now
           full-path stems (e.g. 'arch/arm/kernel/setup') rather than bare
           basenames ('setup').  This is produced by st03 _extract_log_objects()
           v16.3.0.

           Routing in build_compiled_sets():
           - Entries that contain a directory component (os.path.dirname non-empty)
             are added directly to artifact_stems.  The existing _file_has_artifact()
             full-path-stem lookup handles them with no further change, and the
             cross-architecture false-positive (arch/s390/kernel/setup.c matching
             a log entry for arch/arm/kernel/setup.o) is eliminated.
           - Entries with no directory component (bare basename stem, produced
             when the build log token had no path) are still added to log_basenames
             so the existing directory-scoped fallback in _file_has_artifact()
             is preserved for that edge case.

           _has_real_artifact_evidence() and _dir_has_artifact_coverage() are
           unchanged; they continue to check artifact_stems and log_basenames
           respectively, and both benefit automatically from the rerouting above.

v16.4.0 changes (J -- DTB artifact coverage for DTS/DTSI files):
  J     -- build_compiled_sets(): collects DTB path stems from the two new
           product_map fields produced by st03 v16.4.0:
             built_dtb_stems_from_log      -> full-path stems from DTC log lines
             built_dtb_artifacts_from_dir  -> full-path stems from .dtb/.dtbo
                                              files found in build_dir
           Both sets are merged into a new compiled_sets field 'dtb_stems'.

           _file_is_dts(): new helper -- returns True for .dts and .dtsi files.

           _file_has_dtb(): new helper -- returns True when a .dts/.dtsi file's
           path stem is present in dtb_stems.  The stem is computed by stripping
           the source extension from the file path; no directory normalisation is
           needed because DTB stems always carry the full path.

           _has_dtb_evidence(): new helper -- returns True when dtb_stems is
           non-empty, i.e. the product map contains at least one DTB artifact.

           filter_decision() L2half: DTS/DTSI files now participate in the
           voting loop:
             - DTB hit  -> keep_via_artifact (reason 'build_artifact')
             - No hit but DTB evidence present -> vote_drop
             - No DTB evidence at all -> neutral (falls to L0)

           This closes the false-keep gap for DTS-only commits touching
           boards not in the product build.  A commit like
           "ARM: dts: exynos: fix roles of USB 3.0 ports on Odroid XU"
           that touches only arch/arm/boot/dts/exynos5410-odroidxu.dts
           is now correctly dropped when the product's build artifacts
           contain DTB files for a different board.

           available flag: dtb_stems alone do NOT set available=True
           (they are a supplemental evidence type, not a substitute for
           compiled_files/artifact_stems).  DTS files are only evaluated
           when dtb_stems is non-empty -- ensuring that products without any
           DTB evidence at all fall through to the L0 neutral path.

v16.13.1 changes (K -- prefilter_debug embedded in commit sidecar):
  K     -- run(): filter_decision() debug dict is now attached directly to every
           commit as c['prefilter_debug'] (both kept and dropped) in addition to
           being aggregated into prefilter_debug.json.

           The prefilter_debug field is included in the canonical JSON key
           ordering produced by order_commit_details() (lib/scoring.py).

prefilter_debug field schema (v16.13.1, embedded per commit):
  {
    "sha":                            <str>,
    "files":                          [<str>, ...],
    "filter_enabled":                 <bool>,
    "kconfig_required":               <bool>,
    "l3_commit_wl_match":             {pattern, value} | null,
    "l3_commit_bl_match":             {pattern, value} | null,
    "l2a_path_bl_matches":            [{pattern, file}, ...],
    "l2half_has_real_artifacts":      <bool>,
    "l2half_artifact_files":          [<str>, ...],
    "l2half_kconfig_covered_files":   [<str>, ...],
    "l2half_kconfig_uncovered_files": [<str>, ...]
  }

prefilter_debug.json aggregate schema (written to cache dir):
  {
    "summary": {
      "total_commits": <int>,
      "kept":          <int>,
      "dropped":       <int>,
      "drop_reasons":  {<reason>: <int>, ...}
    },
    "dropped": [
      {
        "sha":        <str>,
        "sha12":      <str>,
        "drop_reason": <str>,
        "subject":    <str>,
        "author":     <str>,
        "files":      [<str>, ...],
        "debug":      { ... }
      },
      ...
    ]
  }
"""
import csv
import json
import logging
import os
import re
import sys

from lib.config import save_json
from lib.patterns import (
    match as _match,
    anyfilematches as _any_file_matches,
    allfilesmatch as _all_files_match,
)
from lib.pipeline_runtime import update_stage_progress, finish_progress_line
from lib.profile_rules import load_profile_rules
from lib.scoring import extract_commit_meta, precompile_rules, fmt_profiles, fmt_evidence
from lib.kbuild import infer_touched_paths
from lib.manifest import CACHE_FILES, NSTAGES
from lib.schema import validate_commit_list, validate_filtered_commit_list

_BUILD_SYS_NAMES = frozenset({'Makefile', 'Kbuild', 'Kconfig'})
_HEADER_EXTENSIONS = frozenset({'.h', '.hpp', '.hxx', '.h++'})
_SOURCE_EXTENSIONS = frozenset({'.c', '.S', '.cc', '.cpp', '.cxx', '.c++'})
_DTS_EXTENSIONS    = frozenset({'.dts', '.dtsi'})


def _is_build_system_file(path):
    base = os.path.basename(path)
    if base in _BUILD_SYS_NAMES:
        return True
    if base.startswith('Makefile.') or base.startswith('Kconfig.'):
        return True
    _, ext = os.path.splitext(base)
    return ext in ('.mk',)


def _file_is_header(path):
    """Return True if *path* is a C/C++ header file.

    Headers never produce a build artifact directly (.h -> no .o).
    They are always evaluated against kconfig coverage regardless of whether
    real artifact evidence is available.
    """
    _, ext = os.path.splitext(path)
    return ext in _HEADER_EXTENSIONS


def _file_is_source(path):
    """Return True if *path* is a compiled source file (.c, .S, .cc, …).

    Source files produce build artifacts (.o/.ko).  When real artifact evidence
    is present (artifact_stems or log_basenames non-empty), only a direct
    artifact hit counts as evidence for a source file; kconfig coverage alone
    is insufficient.
    """
    _, ext = os.path.splitext(path)
    return ext in _SOURCE_EXTENSIONS


def _file_is_dts(path):
    """Return True if *path* is a DTS or DTSI file.

    v16.4.0 (J): DTS/DTSI files are evaluated against DTB artifact stems
    rather than Kconfig coverage.  A DTS file produces exactly one DTB output
    whose path stem matches the source file's path stem (with extension swapped
    from .dts/.dtsi to .dtb/.dtbo).  When the product's build produced DTB
    artifacts, a DTS file that has no matching DTB is for a board not built
    by the product.
    """
    _, ext = os.path.splitext(path)
    return ext in _DTS_EXTENSIONS


def _has_real_artifact_evidence(cs):
    """Return True when the product_map contains real build-tree artifacts.

    'Real' means built_artifacts_from_dir or built_objects_from_log were
    supplied by the user; config_enabled_map alone does NOT count as artifact
    evidence.  This distinction matters for source files: when real artifacts
    are available, a source file not found in artifact_stems is confidently
    absent from the build.  Without real artifacts, kconfig coverage is used
    as a proxy.
    """
    return bool(cs.get('artifact_stems') or cs.get('log_basenames'))


def _has_dtb_evidence(cs):
    """Return True when the product_map contains DTB artifact stems.

    v16.4.0 (J): when True, DTS/DTSI files can be evaluated against dtb_stems.
    When False (no DTB artifacts at all), DTS files are neutral and fall
    through to the L0 default keep, preserving the pre-J behaviour for
    products that do not provide DTB build output.
    """
    return bool(cs.get('dtb_stems'))


def _file_has_dtb(path, cs):
    """Return True if *path* (a .dts/.dtsi file) has a matching DTB artifact.

    v16.4.0 (J): the stem of a DTS source file matches the DTB output stem
    exactly -- only the extension differs (.dts/.dtsi vs .dtb/.dtbo).  Strip
    the source extension and check for membership in dtb_stems.

    Example:
      path = 'arch/arm/boot/dts/exynos5410-odroidxu.dts'
      stem = 'arch/arm/boot/dts/exynos5410-odroidxu'
      dtb_stems contains 'arch/arm/boot/dts/exynos5410-odroidxu'  -> True

    No trailing-slash normalisation is needed here because DTB stems always
    carry the full relative path (guaranteed by st03 _extract_dtb_stems_from_log
    and _extract_dtb_stems_from_dir, which both require a directory component).
    """
    stem, _ = os.path.splitext(path)
    return stem in cs.get('dtb_stems', set())


def _dir_has_artifact_coverage(path, cs):
    """Return True when any artifact stem lives under *path*'s parent directory.

    Used as a path-prefix fallback for build-meta files (Kconfig, Makefile,
    Kbuild, *.mk): if the directory that contains the build-meta file has
    at least one compiled artifact underneath it, the build-meta file is
    considered product-relevant even if its exact directory does not appear
    in compiled_dirs.

    Example: drivers/usb/Kconfig is kept when drivers/usb/core/hub is in
    artifact_stems (drivers/usb/ is a prefix of drivers/usb/core/).

    Root exception: files at the kernel root (os.path.dirname returns '')
    are always considered covered -- the top-level Kconfig and Makefile are
    unconditionally product-relevant.
    """
    fdir = os.path.dirname(path)
    if not fdir:
        return True  # root-level build-meta always relevant
    fdir_slash = fdir.rstrip('/') + '/'
    if fdir_slash in cs['compiled_dirs']:
        return True
    return any(s.startswith(fdir_slash) for s in cs['artifact_stems'])


def build_compiled_sets(product_map):
    """Build the compiled_sets lookup structure used by _file_has_artifact() and
    _file_is_kconfig_covered().

    v13.0.1 (H): reads config_enabled_map and config_enabled_dirs from
    product_map instead of config_to_paths.  config_enabled_map is the
    enabled-symbol-only subset computed by st03 _filter_to_enabled(); it
    contains only CONFIG symbols that are =y or =m in the product .config.

    Falls back gracefully when config_enabled_map is absent (pre-v13.0.1 cache).

    v13.0.2 (Bug-2 fix): available=True is set based on whether ANY evidence
    source is non-empty (config_enabled_map, built_artifacts_from_dir, or
    built_objects_from_log), not solely on config_enabled_map.

    v16.3.0 (H.2): built_objects_from_log entries are now full-path stems
    (e.g. 'arch/arm/kernel/setup') produced by st03 _extract_log_objects()
    v16.3.0.  Routing:
    - Entries with a directory component go directly into artifact_stems for
      precise full-path matching, eliminating cross-architecture false positives.
    - Entries without a directory component (bare basename stems from log tokens
      that had no path) continue to go into log_basenames so the existing
      directory-scoped fallback in _file_has_artifact() is preserved.

    v16.4.0 (J): collects DTB stems from two new product_map fields:
      built_dtb_stems_from_log      -> stems extracted from DTC log lines
      built_dtb_artifacts_from_dir  -> stems from .dtb/.dtbo files in build_dir
    Both are merged into the new 'dtb_stems' set.  dtb_stems do NOT affect
    the available flag (DTB evidence alone does not activate the kconfig filter).

    Design contract:
      available=True  -> at least one evidence source is non-empty; commits with
                         zero coverage across all sources are confidently dropped.
      available=False -> all evidence sources empty; kconfig filter inactive;
                         scoring resolves ambiguities (correct when the user
                         provides kernel sources only, with no .config/logs/dir).
    """
    empty = dict(compiled_files=set(), compiled_dirs=set(),
                 artifact_stems=set(), log_basenames=set(),
                 dtb_stems=set(), available=False)
    if not product_map:
        return empty

    cem = product_map.get('config_enabled_map')
    if cem is None:
        logging.warning(
            'build_compiled_sets: config_enabled_map not found in product_map '
            '(cache pre-dates v13.0.1). Re-run stage 03 to fix. '
            'Falling back to empty compiled set to avoid false-positive keeps.')
        return empty

    compiled_files = set()
    for paths in cem.values():
        compiled_files.update(paths)

    ced = product_map.get('config_enabled_dirs') or []
    compiled_dirs = set(d for d in ced if d)

    artifact_stems = set()
    for p in (product_map.get('built_artifacts_from_dir', []) or []):
        stem, _ = os.path.splitext(p)
        artifact_stems.add(stem)

    # v16.3.0 (H.2): built_objects_from_log now stores full-path stems when
    # the build-log token had a directory component, and bare basename stems
    # when it did not.  Route accordingly:
    #   - full-path stem (has directory) -> artifact_stems (precise match)
    #   - bare basename stem (no directory) -> log_basenames (dir-scoped fallback)
    log_basenames = set()
    for p in (product_map.get('built_objects_from_log', []) or []):
        stem, _ = os.path.splitext(p)
        if os.path.dirname(stem):
            artifact_stems.add(stem)
        else:
            log_basenames.add(stem)

    # v16.4.0 (J): collect DTB stems from both log and dir sources
    dtb_stems = set()
    for stem in (product_map.get('built_dtb_stems_from_log', []) or []):
        dtb_stems.add(stem)
    for stem in (product_map.get('built_dtb_artifacts_from_dir', []) or []):
        dtb_stems.add(stem)

    has_evidence = bool(compiled_files or artifact_stems or log_basenames)
    if not has_evidence:
        logging.info(
            'build_compiled_sets: no compiled-file evidence found in product_map '
            '(config_enabled_map={}, no build artifacts, no build log). '
            'kconfig coverage filter will be inactive; scoring will resolve ambiguities.')

    return dict(compiled_files=compiled_files, compiled_dirs=compiled_dirs,
                artifact_stems=artifact_stems, log_basenames=log_basenames,
                dtb_stems=dtb_stems, available=has_evidence)


def _file_has_artifact(f, cs):
    """Return True if *f* has build-artifact evidence.

    Two evidence sources are checked in order:

    1. ``artifact_stems`` -- full path stems derived from ``built_artifacts_from_dir``
       and from ``built_objects_from_log`` entries that contained a directory
       component (v16.3.0 H.2).  A full-path stem match is precise and needs no
       further qualification.

    2. ``log_basenames`` -- bare filename stems from ``built_objects_from_log``
       entries that had no directory component in the build log token (v16.3.0 H.2).
       Directory-scoped: a log-basename hit is only accepted when the file's parent
       directory is in ``compiled_dirs`` or the file itself is in ``compiled_files``.

    Trailing-slash normalisation (v16.0.1):
       ``compiled_dirs`` stores entries with a trailing slash (as produced by st03
       ``_derive_config_dirs()``), while ``os.path.dirname()`` returns paths without
       one.  The directory lookup is normalised here so that the membership test
       is reliable.  This is the same normalisation applied in
       ``_file_is_kconfig_covered()`` since v16.0.0.

    Note: DTS/DTSI files should be checked via _file_has_dtb() instead.
    """
    stem, _ = os.path.splitext(f)
    if stem in cs['artifact_stems']:
        return True

    bn_stem, _ = os.path.splitext(os.path.basename(f))
    if bn_stem not in cs['log_basenames']:
        return False
    fdir = os.path.dirname(f)
    fdir_norm = (fdir.rstrip('/') + '/') if fdir else ''
    return (
        (fdir and fdir_norm in cs['compiled_dirs'])
        or f in cs['compiled_files']
    )


def _file_is_kconfig_covered(f, cs):
    """Return True if *f* is considered covered by the product build.

    Coverage is established by three evidence sources, checked in order:

    1. ``compiled_files`` -- exact path match against the set of source files
       associated with enabled CONFIG symbols (config_enabled_map).  This is
       the most precise evidence.

    2. ``compiled_dirs`` -- the file's parent directory (normalised to the
       trailing-slash form stored by st03 _derive_config_dirs, e.g.
       ``"drivers/usb/core/"``) is present in the set of directories derived
       from enabled CONFIG symbols.  A file in a compiled directory is
       considered product-relevant even when it does not appear directly in
       compiled_files (e.g. inline headers, generated stubs).

    3. Build-system files (Kconfig, Makefile, Kbuild, *.mk) -- covered *only*
       when their own directory satisfies rule 2 above, OR when they live at
       the kernel root (os.path.dirname returns '').

       v16.0.0 (C): prior to this version, _is_build_system_file() returned an
       unconditional True for any such file regardless of its location.  This
       caused false-keeps for commits like "btrfs: add Kconfig option for ..."
       that touch fs/btrfs/Kconfig when CONFIG_BTRFS_FS is absent from the
       product .config -- the file matched the build-system check and bypassed
       kconfig coverage entirely.

       The root exception (fdir == '') preserves correct behaviour for the
       kernel's top-level Kconfig and Makefile, which are unconditionally
       product-relevant regardless of which CONFIG symbols are enabled.

    Trailing-slash normalisation (v16.0.0):
       st03 _derive_config_dirs() stores directory paths with a trailing slash
       (e.g. ``"drivers/usb/core/"``), while os.path.dirname() returns paths
       without one (e.g. ``"drivers/usb/core"``).  The lookup is normalised
       here so that the membership test is reliable for all file types.
    """
    if f in cs['compiled_files']:
        return True

    fdir = os.path.dirname(f)
    # compiled_dirs stores trailing-slash normalised paths (e.g. "drivers/usb/core/").
    # os.path.dirname returns paths without a trailing slash.  Normalise before
    # lookup so the membership test is reliable for all file types.
    fdir_norm = (fdir.rstrip('/') + '/') if fdir else ''

    if fdir and fdir_norm in cs['compiled_dirs']:
        return True

    # Build-system files (Kconfig, Makefile, Kbuild, *.mk): product-relevant
    # only when their directory is compiled into the product, or when they live
    # at the kernel root (fdir == '').  The compiled_dirs check above already
    # handles the "directory is compiled" case; we reach here only when it did
    # not match, so we apply the root exception only.
    if _is_build_system_file(f):
        return not fdir   # True only at root level (fdir == '')

    return False


# -- Pattern repr helper -------------------------------------------------------

def _pat_repr(pat):
    return getattr(pat, 'pattern', str(pat))


def _collect_file_hits(patterns, files):
    """Return list of {pattern, file} for each matching (pattern, file) pair."""
    hits = []
    seen = set()
    for pat in (patterns or []):
        for f in (files or []):
            if _match(pat, f):
                key = (_pat_repr(pat), f)
                if key not in seen:
                    seen.add(key)
                    hits.append({'pattern': _pat_repr(pat), 'file': f})
    return hits


def _collect_hits(patterns, values):
    """Return list of {pattern, value} for each matching (pattern, value) pair."""
    hits = []
    seen = set()
    for pat in (patterns or []):
        for val in (values or []):
            if _match(pat, val):
                key = (_pat_repr(pat), val)
                if key not in seen:
                    seen.add(key)
                    hits.append({'pattern': _pat_repr(pat), 'value': val})
    return hits


def _build_prefilter_debug_entry(commit, drop_reason, debug_detail):
    """Build a structured debug entry dict for a single commit decision.

    Used to populate the 'dropped' list in prefilter_debug.json.
    Also retained as a public helper for use by external tooling and tests.

    Returns a dict with keys:
      sha        -- full SHA (truncated to 40 characters)
      sha12      -- first 12 characters of SHA
      drop_reason-- the filter reason string
      subject    -- commit subject line
      author     -- author name
      files      -- list of commit files
      debug      -- the debug_detail dict from filter_decision()
    """
    sha = (commit.get('commit') or '')[:40]
    return {
        'sha':         sha,
        'sha12':       sha[:12],
        'drop_reason': drop_reason,
        'subject':     commit.get('subject', ''),
        'author':      commit.get('author_name', ''),
        'files':       list(commit.get('files', []) or []),
        'debug':       debug_detail,
    }


# -- Main filter decision ------------------------------------------------------

def filter_decision(commit, compiled_sets, filter_cfg, kconfig_enabled):
    """Return (action, reason, debug_detail): action='keep'|'drop'.

    v14.1.0 (B): `lists` parameter removed.  The filter no longer accepts or
    evaluates keyword whitelist/blacklist or path whitelist patterns.  Those
    are scoring concepts handled exclusively by stage 05.

    v16.1.0 (F): L2half replaced with a per-file type-aware voting loop.
    See module docstring for the full decision table.

    v16.4.0 (J): DTS/DTSI files added to the voting loop.
    See module docstring for the DTS/DTSI evaluation rule.

    v16.13.1 (K): debug_detail is attached to the commit as c['prefilter_debug']
    for both kept and dropped commits.  Dropped commits are also collected into
    prefilter_debug.json via _build_prefilter_debug_entry().

    Only the following signals are evaluated:
      L3  SHA whitelist / blacklist  -- explicit operator per-commit overrides
      L2a path_blacklist ALL files   -- structural path exclusions
      L2half file-type-aware voting  -- per-file keep/drop votes
      L0  default keep

    debug_detail keys:
      sha                           -- commit SHA
      files                         -- list of commit files evaluated
      filter_enabled                -- bool
      kconfig_required              -- bool
      l3_commit_wl_match            -- {pattern, value} or None
      l3_commit_bl_match            -- {pattern, value} or None
      l2a_path_bl_matches           -- [{pattern, file}, ...]
      l2half_has_real_artifacts     -- bool: artifact_stems or log_basenames non-empty
      l2half_artifact_files         -- [file, ...] with artifact evidence
      l2half_kconfig_covered_files  -- [file, ...] with kconfig coverage
      l2half_kconfig_uncovered_files-- [file, ...] without kconfig coverage
    """
    sha   = commit.get('commit', '') or ''
    files = list(commit.get('files', []) or [])

    commit_wl = (filter_cfg or {}).get('commit_whitelist', []) or []
    commit_bl = (filter_cfg or {}).get('commit_blacklist', []) or []
    path_bl   = (filter_cfg or {}).get('path_blacklist',   []) or []

    enabled = (filter_cfg or {}).get('enabled', True)
    require = (filter_cfg or {}).get('require_kconfig_coverage', None)
    if require is None:
        require = compiled_sets.get('available', False) and kconfig_enabled

    # -- Pre-compute L3 hit info -----------------------------------------------
    l3_wl_match = None
    if commit_wl:
        hits = _collect_hits(commit_wl, [sha])
        if hits:
            l3_wl_match = hits[0]

    l3_bl_match = None
    if commit_bl:
        hits = _collect_hits(commit_bl, [sha])
        if hits:
            l3_bl_match = hits[0]

    # -- Pre-compute kconfig coverage (always, so debug is accurate) -----------
    kconfig_covered   = []
    kconfig_uncovered = []
    if kconfig_enabled and require and files:
        for f in files:
            if _file_is_kconfig_covered(f, compiled_sets):
                kconfig_covered.append(f)
            else:
                kconfig_uncovered.append(f)

    # -- Pre-compute artifact evidence (compute once, reuse) -------------------
    artifact_files = []
    if files and compiled_sets.get('available'):
        artifact_files = [f for f in files if _file_has_artifact(f, compiled_sets)]

    # -- Real artifact flag (v16.1.0) ------------------------------------------
    real_artifacts = _has_real_artifact_evidence(compiled_sets)

    # -- Build debug_detail dict -----------------------------------------------
    def _debug():
        return {
            'sha':                            sha,
            'files':                          files,
            'filter_enabled':                 enabled,
            'kconfig_required':               require if (kconfig_enabled and compiled_sets.get('available')) else False,
            'l3_commit_wl_match':             l3_wl_match,
            'l3_commit_bl_match':             l3_bl_match,
            'l2a_path_bl_matches':            [],
            'l2half_has_real_artifacts':      real_artifacts,
            'l2half_artifact_files':          artifact_files,
            'l2half_kconfig_covered_files':   kconfig_covered,
            'l2half_kconfig_uncovered_files': kconfig_uncovered,
        }

    # ========== Filter hierarchy ==============================================

    # L3 SHA whitelist (absolute keep)
    if l3_wl_match:
        return 'keep', 'commit_whitelist', _debug()

    # L3 SHA blacklist (absolute drop)
    if l3_bl_match:
        return 'drop', 'commit_blacklist', _debug()

    # Filter globally disabled
    if not enabled:
        return 'keep', 'filter_disabled', _debug()

    # Zero-file commits (merge commits, tag objects): always keep
    if not files:
        return 'keep', 'no_files_layer', _debug()

    # L2a path blacklist (ALL files must match for drop)
    if path_bl and _all_files_match(path_bl, files):
        d = _debug()
        d['l2a_path_bl_matches'] = _collect_file_hits(path_bl, files)
        return 'drop', 'path_blacklist_all', d

    # L2half -- file-type-aware voting (v16.1.0 / F, v16.4.0 / J)
    if compiled_sets.get('available') or _has_dtb_evidence(compiled_sets):
        keep_via_artifact = []   # direct artifact hit
        keep_via_kconfig  = []   # kconfig/dir coverage hit
        vote_drop         = []   # file actively votes DROP
        # 'other' files are neutral and do not appear in any list

        dtb_evidence = _has_dtb_evidence(compiled_sets)

        for f in files:
            if _file_is_dts(f):
                # v16.4.0 (J): DTS/DTSI files evaluated against DTB stems.
                # Neutral when no DTB evidence exists (pre-J products).
                if dtb_evidence:
                    if _file_has_dtb(f, compiled_sets):
                        keep_via_artifact.append(f)
                    else:
                        vote_drop.append(f)
                # else: no DTB evidence -> neutral

            elif compiled_sets.get('available'):
                if _file_is_source(f):
                    # Source files: artifact is the authoritative evidence.
                    # Fall back to kconfig only when no real artifacts exist.
                    if f in artifact_files:
                        keep_via_artifact.append(f)
                    elif real_artifacts:
                        # Real artifacts available but this file has none -> not built
                        vote_drop.append(f)
                    elif kconfig_enabled and require:
                        if _file_is_kconfig_covered(f, compiled_sets):
                            keep_via_kconfig.append(f)
                        else:
                            vote_drop.append(f)
                    # else: no real artifacts, require inactive -> neutral

                elif _file_is_header(f):
                    # Header files: never produce artifacts; always use kconfig.
                    if kconfig_enabled and require:
                        if _file_is_kconfig_covered(f, compiled_sets):
                            keep_via_kconfig.append(f)
                        else:
                            vote_drop.append(f)
                    # else: require inactive -> neutral

                elif _is_build_system_file(f):
                    # Build-meta files: kconfig dir coverage first;
                    # path-prefix artifact fallback when real artifacts present.
                    if _file_is_kconfig_covered(f, compiled_sets):
                        keep_via_kconfig.append(f)
                    elif real_artifacts and _dir_has_artifact_coverage(f, compiled_sets):
                        keep_via_artifact.append(f)
                    elif kconfig_enabled and require:
                        vote_drop.append(f)
                    # else: neutral

                # other files (docs, txt, MAINTAINERS, …): neutral, skip

        if keep_via_artifact:
            return 'keep', 'build_artifact', _debug()
        if keep_via_kconfig:
            return 'keep', 'kconfig_coverage', _debug()
        if vote_drop:
            return 'drop', 'no_kconfig_coverage', _debug()

    # L0 default keep
    return 'keep', 'default', _debug()


def run(cfg, cache):
    """Enrich + filter commits. Returns (kept, dropped_commits, reasons).

    v16.13.1 (K): filter_decision() debug dict is attached to every commit as
    c['prefilter_debug'] (both kept and dropped).  Dropped commits are also
    aggregated into prefilter_debug.json via _build_prefilter_debug_entry().
    """
    from lib.config import load_json

    filter_cfg  = cfg.get('filter', {}) or {}
    commits     = load_json(os.path.join(cache, CACHE_FILES['commits']), default=[]) or []
    validate_commit_list(commits)
    product_map = load_json(os.path.join(cache, CACHE_FILES['product_map']), default={}) or {}

    # Enrichment
    print('  enriching commits ...')
    total = len(commits)
    step  = max(1, total // 50)
    for i, c in enumerate(commits):
        c['meta']                 = extract_commit_meta(c)
        c['_touched_paths_guess'] = infer_touched_paths(c.get('subject', ''), cfg)
        if i % step == 0 or i == total - 1:
            update_stage_progress(4, NSTAGES, 0.4 * (i + 1) / max(total, 1),
                                  'enriching', n_done=i + 1, n_total=total)
    sys.stdout.write('\n')

    compiled_sets  = build_compiled_sets(product_map)
    kconfig_active = compiled_sets.get('available', False)

    commit_wl = filter_cfg.get('commit_whitelist', []) or []
    commit_bl = filter_cfg.get('commit_blacklist', []) or []
    path_bl   = filter_cfg.get('path_blacklist',   []) or []

    print('  compiled_files  : %d' % len(compiled_sets['compiled_files']))
    print('  compiled_dirs   : %d' % len(compiled_sets['compiled_dirs']))
    print('  artifact_stems  : %d' % len(compiled_sets['artifact_stems']))
    print('  log_basenames   : %d' % len(compiled_sets['log_basenames']))
    print('  dtb_stems       : %d' % len(compiled_sets['dtb_stems']))
    print('  commit_wl       : %d patterns' % len(commit_wl))
    print('  commit_bl       : %d patterns' % len(commit_bl))
    print('  path_bl         : %d patterns' % len(path_bl))
    print('  kconfig_active  : %s' % kconfig_active)

    kept            = []
    dropped_commits = []
    debug_entries   = []   # for prefilter_debug.json aggregate
    reasons         = {}

    for i, c in enumerate(commits):
        action, reason, dbg = filter_decision(c, compiled_sets, filter_cfg, kconfig_active)
        # v16.13.1 (K): attach debug dict to the commit itself (kept and dropped alike)
        c['prefilter_debug'] = dbg
        if action == 'drop':
            c['_filter_reason'] = reason
            reasons[reason] = reasons.get(reason, 0) + 1
            dropped_commits.append(c)
            debug_entries.append(_build_prefilter_debug_entry(c, reason, dbg))
        else:
            kept.append(c)
        if i % step == 0 or i == total - 1:
            update_stage_progress(4, NSTAGES, 0.4 + 0.6 * (i + 1) / max(total, 1),
                                  'filtering', n_done=i + 1, n_total=total)
    sys.stdout.write('\n')
    sys.stdout.flush()

    validate_commit_list(kept)
    validate_filtered_commit_list(dropped_commits)
    save_json(os.path.join(cache, CACHE_FILES['prefilter_kept']), kept)
    save_json(os.path.join(cache, CACHE_FILES['filtered']), dropped_commits)

    # Write prefilter_debug.json aggregate
    # Summary uses test-expected keys: total_commits, kept, dropped, drop_reasons
    debug_output = {
        'summary': {
            'total_commits': total,
            'kept':          len(kept),
            'dropped':       len(dropped_commits),
            'drop_reasons':  dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        },
        'dropped': debug_entries,
    }
    save_json(os.path.join(cache, CACHE_FILES['prefilter_debug']), debug_output)

    reason_summary = {}
    for r, cnt in sorted(reasons.items(), key=lambda kv: -kv[1]):
        reason_summary[r] = cnt

    logging.debug(
        'prefilter: kept=%d dropped=%d reasons=%s',
        len(kept), len(dropped_commits), reason_summary,
    )

    return kept, dropped_commits, reasons


def write_outputs(cfg, dropped_commits, outdir):
    """Write filtered output files (JSON, CSV, HTML, XLSX, ODS)."""
    from lib.spreadsheet import COMMIT_COLS, write_xlsx, write_ods
    reports = cfg.get('reports', {}) or {}
    os.makedirs(outdir, exist_ok=True)

    jp = os.path.join(outdir, 'filtered_commits.json')
    with open(jp, 'w', encoding='utf-8') as f:
        json.dump(dropped_commits, f, indent=2, default=str)
    print('  filtered JSON: %s' % jp)

    if reports.get('outputs') and 'csv' in (reports.get('outputs') or []):
        cp = os.path.join(outdir, 'filtered_commits.csv')
        with open(cp, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(list(COMMIT_COLS) + ['Filter reason'])
            for c in dropped_commits:
                w.writerow([
                    c.get('_rank', ''),
                    (c.get('commit') or '')[:12],
                    c.get('subject', ''),
                    c.get('author_name', ''),
                    c.get('author_time', ''),
                    c.get('score', 0) or 0,
                    fmt_profiles(c),
                    fmt_evidence(c),
                    c.get('_filter_reason', ''),
                ])
        print('  filtered CSV:  %s' % cp)

    if reports.get('outputs') and 'html' in (reports.get('outputs') or []):
        try:
            from lib.html_report import generate_html_report
            hp = os.path.join(outdir, 'filtered_commits.html')
            title = reports.get('title', 'kcommit Analysis Report') + ' -- Filtered'
            generate_html_report(dropped_commits, {}, {}, hp, title=title, is_filtered=True,
                          templates_dir=cfg['paths'].get('templates_dir'))
            print('  filtered HTML: %s' % hp)
        except Exception as e:
            logging.warning('filtered HTML failed: %s', e)

    if reports.get('outputs') and 'xlsx' in (reports.get('outputs') or []):
        try:
            xp = os.path.join(outdir, 'filtered_commits.xlsx')
            write_xlsx(xp, dropped_commits, {})
            print('  filtered XLSX: %s' % xp)
        except Exception as e:
            logging.warning('filtered XLSX failed: %s', e)

    if reports.get('outputs') and 'ods' in (reports.get('outputs') or []):
        try:
            op = os.path.join(outdir, 'filtered_commits.ods')
            write_ods(op, dropped_commits, {})
            print('  filtered ODS:  %s' % op)
        except Exception as e:
            logging.warning('filtered ODS failed: %s', e)
