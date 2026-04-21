# Reports Guide

Main outputs include `relevant_commits.csv`, `relevant_commits.json`, `profile_matrix.csv`, and `profile_summary.json`.
## V7.0 scoring evidence

Reports now include:
- `stable_score` for commits that look stable-fix oriented,
- `product_evidence` to show whether a commit matched build-log evidence, build-dir artifact evidence, config-derived evidence, or only a weak textual path guess.
