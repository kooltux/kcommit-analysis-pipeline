# Architecture

## Pipeline overview

```
00_prepare_pipeline.py
  Validate config, compile profiles/rules, init workspace state
  → cache/compiled_rules.json, cache/prepare_summary.json

01_collect_commits.py
  git log rev_old..rev_new — collect commit metadata + file lists
  → cache/commits.json

02_collect_build_context.py
  Read kernel .config, build artifacts, build logs (kernel + Yocto), DTS roots
  → cache/build_context.json, cache/kbuild_static_map.json

03_build_product_map.py
  Map Kconfig symbols → source paths using .config + build context
  → cache/product_map.json

04_filter_commits.py                 ← NEW in v8.11 (replaces 04_enrich_commits.py)
  1. Enrich each commit with stable_hints + touched_paths_guess
  2. Drop commits that cannot possibly score:
       Rule 1: SHA in any profile's commit_blacklist
       Rule 2: ALL touched files match merged path_blacklist (opt-in per config)
       Rule 3: No touched file in product map (opt-in, filter.require_product_map)
  → cache/filtered_commits.json

05_score_commits.py
  Score filtered commits via profile/rule matching only (parallel workers)
  → cache/scored_commits.json

06_report_commits.py
  Apply min_score threshold, sort, generate outputs
  → output/relevant_commits.csv
  → output/relevant_commits.json
  → output/profile_summary.json
  → output/profile_matrix.csv
  → output/report_stats.json
  → output/summary.html
```

## Scoring model (v8.11)

**Score = sum of per-profile rule contributions only.**

```
for each active profile P with weight W:
    per_rule = sum(rule.weight for each rule that matches the commit)
    per_rule = min(per_rule, 100)                    # cap at 100 per profile
    profile_score[P] = int(per_rule × W / 100)

combined_score = Σ profile_score[P]
```

### What does NOT contribute to the score

Security keyword detection, CVE detection, stable/fix trailer detection,
performance keyword detection, and product-map evidence are computed and stored
as metadata under `commit['scoring']['meta']`. They are displayed as flag
badges in the HTML report (CVE / Fix / Stable / Perf) but **do not add to the
score**. The only way to influence scoring is through profile weights and rule
weights in the config repository.

### Why this model

Keeping scoring exclusively in profiles/rules makes the system:
- **Auditable**: every score point traces back to a rule file and a pattern.
- **Tunable**: adjusting a rule weight or profile weight has predictable effect.
- **Deterministic**: no implicit global bonus that changes across versions.

## Pre-scoring filter (stage 04)

The filter eliminates structurally irrelevant commits *before* scoring runs.
This reduces scoring work and keeps output focused on commits that can
actually receive a non-zero score through the configured rule sets.

```
filter.enabled = true  (default)
│
├─ Rule 1 (always active, even if enabled=false):
│   commit SHA ∈ any profile's commit_blacklist → DROP
│
├─ Rule 2 (filter.path_blacklist_global, default true):
│   ALL touched files match merged path_blacklist → DROP
│   Example: commit touches only Documentation/** → dropped if that
│   path is blacklisted in any active profile.
│
└─ Rule 3 (filter.require_product_map, default false, opt-in):
    NO touched file appears in product_map.config_to_paths → DROP
    Enable only when the product map is comprehensive.
```

Filtered commits are written to `cache/filtered_commits.json`.
Stage 05 reads this file and falls back to `enriched_commits.json` →
`commits.json` for backward compatibility.

## --override deep-merge

`kcommit_pipeline.py --override '{"key":{"sub":"val"}}'` calls
`deep_merge(cfg, patch)` after config loading and `${VAR}` expansion.
The same flag is forwarded to every stage script, so the merged config is
consistent across all stages in a single pipeline run.

`deep_merge()` and `apply_override()` are defined in `kcommit_pipeline.py`
and importable by stage scripts:

```python
from kcommit_pipeline import apply_override
apply_override(cfg, args.override)
```

## File roles

| File | Role |
|------|------|
| `MANIFEST.json` | Version string, pipeline stage list — single source of truth |
| `lib/manifest.py` | Reads `VERSION` from `MANIFEST.json` |
| `lib/config.py` | Comment-aware JSON loader, `${VAR}` expansion, `cfg['paths']` |
| `lib/profile_rules.py` | Profile + rule loading, merging, LRU cache |
| `lib/scoring.py` | `score_commit()` — profile/rule scoring; `extract_stable_hints()` |
| `lib/html_report.py` | HTML report: dark mode, Satoshi font, gradient header, score badges |
| `lib/spreadsheet.py` | XLSX (stdlib zipfile) and ODS export |
| `lib/validation.py` | Config validation (full + lightweight variants) |
| `lib/pipeline_runtime.py` | Stage state tracking, progress display, ETA |
| `lib/history_map.py` | Git history → config-symbol-to-path mapping |
| `lib/kbuild.py` | Kbuild/Kconfig static analysis helpers |
| `lib/gitutils.py` | Git subprocess wrappers |
| `lib/parse_kconfig.py` | Kconfig file parser |
