# Configuration

Configuration files are JSON with comment support. Relative paths are resolved from `CONFIGDIR`, the directory of the current config file. Centralize `profiles_dir`, `rules_dir`, `scoring_dir`, and `templates_dir` in `inputs`. The global `scoring` section is only for non-profile extras.

---

## `collect` — additional options (v8.4)

| Key | Type | Default | Description |
|---|---|---|---|
| `collect.jsonl` | bool | `false` | Write `commits.jsonl` (one JSON object per line) alongside `commits.json`. Useful for streaming large result sets into external tooling. |
| `collect.include_parents` | bool | `false` | Attach parent SHAs to each commit dict under a `parents` key. Disabled by default for performance. |
| `collect.use_numstat` | bool | `true` | Attach `--numstat` file-change statistics (`files`, `insertions`, `deletions`). |
| `collect.use_no_merges` | bool | `true` | Pass `--no-merges` to `git log`. |
| `collect.use_first_parent` | bool | `false` | Pass `--first-parent` to `git log`. |
| `collect.max_commits` | int | `0` | Cap the number of commits collected. `0` = no limit. |
| `collect.score_workers` | int | `0` | Parallel scoring workers. `0` = auto (min(4, cpu_count)). |

---

## `history_mapping` options

| Key | Type | Default | Description |
|---|---|---|---|
| `history_mapping.mode` | string | `"range"` | One of `range`, `sampled`, `full`, `disabled`. Validated at startup. |
| `history_mapping.sample_step` | int | `1000` | Sample one revision every N commits. Validated as a positive integer. |
| `history_mapping.max_commits_per_probe` | int | `256` | Maximum revisions probed per Makefile path. |
| `history_mapping.max_failure_rate` | float | `0.05` | If more than this fraction of `git show` tasks fail, the stage fails loudly. |

---

## `tools/generate_message_whitelist.py`

A standalone helper that reads `scored_commits.json` from a previous pipeline
run and writes a `commit_whitelist.txt` rule file containing the SHAs of all
commits whose score exceeds a minimum threshold.

```bash
python3 tools/generate_message_whitelist.py \
    --input    work/output/scored_commits.json \
    --output   configs/profiles/my_product/commit_whitelist.txt \
    --min-score 50
```

Use this to bootstrap a new product profile from a manually-reviewed set of
highly relevant commits, then refine with keyword and path rules.
