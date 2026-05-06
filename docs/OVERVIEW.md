# kcommit-analysis-pipeline — Overview

`kcommit-analysis-pipeline` analyses a range of Linux kernel commits and
identifies those relevant to a given embedded product. It combines build
context (which kernel symbols are enabled), profile-based rule matching, and
a multi-level filter hierarchy to produce a ranked, scored output in HTML,
CSV, XLSX, and ODS formats.

## Pipeline at a glance

```
Stage  Script                      Input → Output (cache/)
─────────────────────────────────────────────────────────────────────────────
  00   00_prepare_pipeline.py      config → 00_compiled_rules.json
                                            00_prepare_summary.json

  01   01_collect_commits.py       git log → 01_commits.json
                                             01_commits.jsonl  (optional)

  02   02_collect_build_context.py kernel .config / build logs / DTS roots
                                   → 02_build_context.json
                                     02_kbuild_static_map.json

  03   03_build_product_map.py     build context + git history
                                   → 03_product_map.json
                                     (CONFIG_* symbol → source file mapping)

  04   04_prefilter_commits.py     01_commits.json + 03_product_map.json
                                   → 04_filtered_commits.json
                                     (keeps only scoreable commits)

  05   05_score_commits.py         04_filtered_commits.json
                                   → 05_scored_commits.json

  06   06_postfilter_commits.py    05_scored_commits.json
                                   → 06_relevant_commits.json  (above threshold)
                                     04_filtered_commits.json  (+ low-score drops)

  07   07_report_commits.py        06_relevant_commits.json
                                   → output/relevant_commits.{json,csv,xlsx,ods}
                                     output/summary.html
                                     output/profile_summary.json
                                     output/profile_matrix.{json,csv}
                                     output/report_stats.json
```

## Scoring model

```
for each active profile P with weight W (0–100):
    rule_sum  = sum(rule.weight for rule in P if rule matches commit)
    rule_sum  = min(rule_sum, 100)          # capped per profile
    score[P]  = int(rule_sum × W / 100)

total_score = Σ score[P]
```

Score is **exclusively** determined by profile weights and rule weights.
Metadata flags (CVE, Fix, Stable, Perf) are computed and shown as badges
in the HTML report but do **not** add to the score.

## Filter hierarchy (stage 04 — prefilter)

```
Level 3 — SHA-based (always active)
  commit_whitelist → FORCE-KEEP  (beats everything)
  commit_blacklist → FORCE-DROP  (beaten only by whitelist)

Level 2 — Path-based
  ALL files ∈ path_blacklist    → DROP
  ANY file  ∈ path_whitelist    → KEEP

Level 2½ — Build context
  ANY file has build artifact evidence → KEEP
  Kconfig-coverage check: if NO file maps to an enabled CONFIG_*
    and NOT saved by path_whitelist / build_artifact / keyword_whitelist
    → DROP

Level 1 — Keyword-based
  ANY keyword ∈ keywords_whitelist → KEEP
  ANY keyword ∈ keywords_blacklist → DROP

Level 0 — Default → KEEP
```

Dropped commits are recorded with their reason in `04_filtered_commits.json`.
After stage 06, commits dropped for low score (`score_below_threshold`) are
appended to the same file so every dropped commit has a reason.

## Running the pipeline

```bash
# Full run
python3 kcommit_pipeline.py --config configs/my-product.json

# Single stage
python3 kcommit_pipeline.py --config configs/my-product.json --stage 5

# Re-run from stage 4 onwards
python3 kcommit_pipeline.py --config configs/my-product.json --from 4

# Validate config without running
python3 kcommit_pipeline.py --config configs/my-product.json --dry-run

# Override a config value at runtime (deep-merged)
python3 kcommit_pipeline.py --config configs/my-product.json \
    --override '{"filter":{"min_score":20}}'
```
