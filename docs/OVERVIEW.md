# kcommit-analysis-pipeline — Overview

Analyses a range of Linux kernel commits and identifies those relevant to a
given embedded product. Build context (enabled kernel symbols), profile-based
rule matching, and a multi-level filter hierarchy produce a ranked, scored
output in HTML, CSV, XLSX, and ODS formats.

## Pipeline at a glance

```
Stage  Module                      Input → Output (cache/)
─────────────────────────────────────────────────────────────────────────────
  00   lib/stages/st00_prepare.py      config → 00_compiled_rules.json
                                            00_prepare_summary.json

  01   lib/stages/st01_collect.py       git log → 01_commits.json

  02   lib/stages/st02_build_context.py kernel .config / build logs / DTS roots
                                   → 02_build_context.json
                                     02_kbuild_static_map.json

  03   lib/stages/st03_product_map.py     build context + git history
                                   → 03_product_map.json

  04   lib/stages/st04_prefilter.py     01_commits.json + 03_product_map.json
                                   → 04_filtered_commits.json

  05   lib/stages/st05_score.py         04_filtered_commits.json
                                   → 05_scored_commits.json

  06   lib/stages/st06_postfilter.py    05_scored_commits.json
                                   → 06_relevant_commits.json
                                     04_filtered_commits.json (+ low-score drops)

  07   lib/stages/st07_report.py        06_relevant_commits.json
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
Metadata flags (CVE, Fix, Cc:stable, Syzbot) are computed for display in the
HTML report as badges but do **not** add to the score.

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
  Kconfig-coverage: if NO file maps to an enabled CONFIG_*
    and NOT saved by path_whitelist / build_artifact / keyword_whitelist → DROP

Level 1 — Keyword-based
  ANY keyword ∈ keywords_whitelist → KEEP
  ANY keyword ∈ keywords_blacklist → DROP

Level 0 — Default → KEEP
```

Dropped commits are recorded with a reason in `04_filtered_commits.json`.
After stage 06, commits dropped for low score are appended to the same file.

## Running the pipeline

```bash
python3 kcommit_pipeline.py run      --config cfg.json
python3 kcommit_pipeline.py run      --config cfg.json --stage 5
python3 kcommit_pipeline.py run      --config cfg.json --from 4
python3 kcommit_pipeline.py run      --config cfg.json --resume
python3 kcommit_pipeline.py validate --config cfg.json
python3 kcommit_pipeline.py status   --config cfg.json
python3 kcommit_pipeline.py report   --config cfg.json --format html
python3 kcommit_pipeline.py dropped  --config cfg.json --reason prefilter
```
