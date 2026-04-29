# kcommit-analysis-pipeline v8.6

Python 3.6+-compatible, restartable pipeline to analyze Linux kernel commits
between two revisions and identify commits relevant to security fixes, security
features, and performance improvements.

## What it does

The pipeline compares two kernel revisions, collects the commit history in
between, gathers product-specific build context (Kconfig, build logs, DTS),
maps enabled Kconfig symbols to effective source paths, **pre-filters
irrelevant commits before scoring**, scores the remaining commits exclusively
through configurable profile/rule sets, and generates CSV, JSON, and HTML
reports for manual review.

## Pipeline stages

| # | Key | Script | Purpose |
|---|-----|--------|---------|
| 0 | `prepare_pipeline`      | `00_prepare_pipeline.py`      | Validate config, compile profiles/rules, init workspace |
| 1 | `collect_commits`       | `01_collect_commits.py`       | Collect commit metadata between the two revisions |
| 2 | `collect_build_context` | `02_collect_build_context.py` | Collect kernel .config, build artifacts, build logs |
| 3 | `build_product_map`     | `03_build_product_map.py`     | Map Kconfig symbols → source paths |
| 4 | `filter_commits`        | `04_filter_commits.py`        | Drop commits that cannot possibly score (path blacklists, product-map) |
| 5 | `score_commits`         | `05_score_commits.py`         | Score commits via profiles and rules only |
| 6 | `report_commits`        | `06_report_commits.py`        | Generate CSV / JSON / HTML / XLSX / ODS reports |

Each stage stores intermediate data in `<work_dir>/cache/` and can be
restarted independently.

## Running the pipeline

```bash
# Run all stages
python3 kcommit_pipeline.py --config /path/to/cfg.json

# Run a single stage
python3 kcommit_pipeline.py --config /path/to/cfg.json --stage filter_commits

# Re-run from stage 4 onwards (wipes downstream cache)
python3 kcommit_pipeline.py --config /path/to/cfg.json --from 4

# Override config values at runtime (deep-merged into loaded config)
python3 kcommit_pipeline.py --config /path/to/cfg.json \
    --override '{"kernel":{"rev_old":"v4.14.111"}}'

# Dry-run: validate config and print resolved values without running
python3 kcommit_pipeline.py --config /path/to/cfg.json --dry-run
```

## `--override` option

`--override` accepts a JSON object that is **deep-merged** into the loaded
config after all `${VAR}` expansion. Nested keys are merged recursively;
scalar values and lists are replaced. Sibling keys not present in the patch
are preserved.

The override is forwarded to every stage script, so the effect is consistent
across all stages when running the full pipeline or a single stage directly.

```bash
# Change the revision range
--override '{"kernel":{"rev_old":"v4.14.111","rev_new":"v4.14.200"}}'

# Disable the pre-scoring filter
--override '{"filter":{"enabled":false}}'

# Lower the reporting threshold
--override '{"templates":{"top_n":200}}'

# Change active profile weights
--override '{"profiles":{"active":{"security_fixes":100,"performance":30}}}'
```

## Scoring model (v8.6)

Scoring is **exclusively through profiles and rules**. There are no direct
score contributions from security keywords, stable hints, CVE detection, or
product-map evidence. Those signals are computed and stored as metadata
(visible in the HTML report as flag badges and in the JSON output under
`scoring.meta`) but do **not** add to the score.

The only way to influence scoring is through:
- **Profile weights** (`profiles.active`) — scale each profile's contribution.
- **Rule weights** (per rule-set directory, `weight` key) — score individual rule hits.
- **Blacklists / whitelists** in rule sets — control which commits and paths match.

### Scoring flow

```
commit
  │
  ├─ profile_blacklist / commit_blacklist → score = 0, skip profile
  │
  ├─ for each active profile:
  │    per_rule_total = sum(rule.weight for matching rules), capped at 100
  │    profile_score  = int(per_rule_total × profile_weight / 100)
  │
  └─ combined score = Σ profile_scores
```

### Pre-scoring filter (stage 04)

Before scoring, stage 04 drops commits that are structurally irrelevant:

1. **SHA blacklist** — commit SHA matches any profile's `commit_blacklist`.
2. **All paths blacklisted** — every file touched matches the merged
   `path_blacklist` from all active profiles (`filter.path_blacklist_global`).
3. **No product-map coverage** — no touched file appears in the compiled
   product map (`filter.require_product_map`, opt-in, default `false`).

Filtered commits are written to `cache/filtered_commits.json`. Stage 05
reads this file (falls back to `enriched_commits.json` → `commits.json`).

## Configuration

Configuration files are JSON with `//` and `#` comment support.

### Variable expansion

`${VAR}` is expanded in all string values:

| Variable    | Value |
|-------------|-------|
| `WORKSPACE` | External workspace root (from shell environment) |
| `TOOLDIR`   | Pipeline repository root (auto-set by config loader) |
| `CONFIGDIR` | Directory of the current config file (auto-set) |
| `CWD`       | Current working directory |

### Directory layout

```
your-product-config/
├── config.json                  ← copy & customize example-arm-embedded-full.json
├── profiles/
│   ├── security_fixes.json
│   ├── security_features.json
│   └── performance.json
├── rules/
│   ├── security_general/
│   │   ├── keywords_whitelist.txt
│   │   ├── keywords_blacklist.txt
│   │   ├── path_whitelist.txt
│   │   ├── path_blacklist.txt
│   │   ├── commit_whitelist.txt
│   │   └── commit_blacklist.txt
│   └── …
└── scoring/
    └── subsystem_path_hints.json
```

### Profile format

```json
{
  "name": "security_fixes",
  "description": "Kernel security fixes — CVE, UAF, OOB, privilege escalation",
  "rules": ["security_cve_bugs", "security_bounds", "security_memory",
            "security_general", "security_auth_caps", "security_crypto_time",
            "security_syscalls"]
}
```

### Rule-set structure

Each sub-directory under `rules_dir` is one rule set. The directory name is
the rule key. Each rule set may contain any of:

| File | Effect |
|------|--------|
| `keywords_whitelist.txt` | Lines matched against commit subject + body; hit adds `weight` |
| `keywords_blacklist.txt` | Lines matched against subject; hit excludes commit from this profile |
| `path_whitelist.txt`     | Lines matched against touched file paths; hit adds `weight` |
| `path_blacklist.txt`     | Lines matched against touched file paths; if ALL files match, commit is filtered (stage 04) |
| `commit_whitelist.txt`   | Exact or glob SHA matches; hit adds `weight` |
| `commit_blacklist.txt`   | Exact or glob SHA matches; hit excludes commit from this profile |

Pattern syntax per line:
- `re:<expr>` — case-insensitive regex
- `*`, `?`, `[…]` — fnmatch glob
- plain text — case-insensitive substring

Rule weight is set in the profile JSON under `rules[name].weight` (default 50).

## Outputs

| File | Description |
|------|-------------|
| `output/relevant_commits.csv`  | Ranked commits above the score threshold |
| `output/relevant_commits.json` | Same data as JSON |
| `output/profile_summary.json`  | Per-profile commit count, total score, avg score |
| `output/profile_matrix.csv`    | Per-commit × per-profile score breakdown |
| `output/report_stats.json`     | Pipeline run statistics |
| `output/summary.html`          | Interactive HTML report (filters, sort, dark mode, score badges) |

Optional: `relevant_commits.xlsx` / `relevant_commits.ods`
(enable with `templates.xls_output` / `templates.ods_output`).

## Example config

`configs/example-arm-embedded-full.json` — fully annotated ARM Linux
`v4.14.206..v4.14.336` example with all available options documented.

## Requirements

- Python 3.6+
- `git` on `PATH`
- No third-party Python packages required (stdlib only)
