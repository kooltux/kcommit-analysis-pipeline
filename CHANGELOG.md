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
