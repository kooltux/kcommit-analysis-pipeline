# Changelog

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
