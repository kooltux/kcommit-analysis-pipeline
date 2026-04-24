# kcommit-analysis-pipeline v7.21

Python 3.6+-compatible, restartable pipeline to analyze Linux kernel commits between two revisions and identify commits relevant to security fixes, security features, and performance improvements.

## What it does

The pipeline compares two kernel revisions, collects the commit history in between, gathers product-specific build context, maps enabled Kconfig options to effective source paths, scores commits against configurable rule sets, and generates CSV, JSON, and HTML reports for manual review.

## Pipeline stages

- `01_collect_commits.py` – collect commit metadata between two revisions.
- `02_build_product_context.py` – gather build context, scan kbuild tree, and build product map.
- `03_enrich_commits.py` – enrich commits with derived hints and touched-path guesses.
- `04_score_commits.py` – score commits using profiles, rules, and non-profile bonus evidence.
- `05_report_commits.py` – generate CSV/JSON reports and the HTML summary.

Each stage stores intermediate data in the workspace cache directory and can be restarted independently.

## Configuration model

Configuration files are JSON with support for comments.

### Variables

The config loader supports `${VAR}` expansion. These variables are available automatically:

- `WORKSPACE` – external workspace root, usually provided through the shell environment.
- `TOOLDIR` – tool repository root.
- `CONFIGDIR` – directory containing the current config file.
- `CWD` – current working directory.

### Relative paths

Any relative path in a config file is resolved relative to `CONFIGDIR`.

### Inputs section

Directory roots that describe the local configuration repository must be centralized in `inputs`:

- `inputs.profiles_dir`
- `inputs.rules_dir`
- `inputs.scoring_dir`
- `inputs.templates_dir`

Lower functional sections (`profiles`, `rules`, `templates`) should not repeat those paths.

## Scoring model

The scoring model is intentionally split into two layers:

1. **Profiles and rules** drive the thematic relevance score.
   - Profiles define analysis axes such as `security_fixes`, `security_features`, and `performance`.
   - Rules define the actual matching criteria and carry local weights.
   - If a commit matches several rules and several profiles, all contributions are combined additively.

2. **Global scoring extras** in the `scoring` section are reserved for non-profile evidence only.
   Typical examples are:
   - product evidence from config-to-path mapping,
   - stable/fix/CVE hints,
   - symbol-level matches,
   - future technical evidence sources.

The `scoring` section must not duplicate profile or rule weights.

## Running the pipeline

Run all stages:

```bash
python3 kcommit_pipeline.py --config /path/to/config.json
```

Run a single stage:

```bash
python3 kcommit_pipeline.py --config /path/to/config.json --stage score_commits
```

Dry-run configuration validation:

```bash
python3 kcommit_pipeline.py --config /path/to/config.json --dry-run
```

## Outputs

The final report stage produces:

- `relevant_commits.csv`
- `relevant_commits.json`
- `profile_summary.json`
- `profile_matrix.csv`
- `report_stats.json`
- HTML summary report

## Examples

The repository ships two ARM-oriented example configurations targeting Linux `v4.14.206..v4.14.336`:

- `configs/example-arm-embedded-default.json`
- `configs/example-arm-embedded-full.json`

They are intended to be copied into a product-specific configuration repository and customized there.
