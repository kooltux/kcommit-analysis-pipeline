# kcommit_analysis_pipeline V5

Python 3.6-compatible, restartable pipeline to analyze Linux kernel commits between two revisions and rank commits for product relevance, security relevance, and performance relevance.

## V5 highlights
- Profile-aware scoring and reporting.
- Rules support plain substrings, fnmatch wildcards, and regular expressions with `re:` prefix.
- Pretty-printed JSON configs.
- Multiple active profiles in one analysis.
- Additional outputs: `profile_matrix.csv` and `profile_summary.json`.
## V6 additions
- Enhanced documentation and usage guides.
- Helper scripts and richer example configs.
- Synthetic validation dataset and HTML summary template.
- Config support for relative includes and `${foo}` pseudo variables.
- Runnable stage skeleton helpers and HTML summary generator.
## V6.4 additions
- vendor-specific TCU-oriented profile rewrite.
- Example vendor-specific TCU configs and matching rule sets.

## V6.5 additions
- Added explanatory comments to the main Python sources so the control flow is easier to follow.
## V6.6 additions
- Added `docs/PROFILE_SETS.md` to explain legacy, vendor-specific TCU, and merged profile groupings.
- Added merged `` profile to cover the full vendor-specific TCU-oriented scope with a single profile.
- Added `configs/example---tcu.json` as a one-profile configuration example.
## V6.7 additions
- Updated example configs so they do not hardcode absolute paths.
- Standardized path construction around the external `WORKSPACE` variable.
- Added `configs/example-workspace-template.json` as a reference template.
## V6.8 additions
- `WORKSPACE` can now be supplied from the shell environment.
- Launch helpers fail early when `WORKSPACE` is not exported.
- Config loading imports the shell-level `WORKSPACE` value before expanding `${WORKSPACE}` paths.
## V6.9 additions
- `kernel.source_dir` and `inputs.kernel_config` are now treated as mandatory inputs.
- `inputs.build_dir` is optional.
- When present, `build_dir` is scanned for `.o` and `.ko` artifacts and the results are added to the captured build context.
## V7.0 additions
- Product scoring now uses evidence from `product_map.json` more explicitly.
- Optional build directory artifacts contribute to relevance scoring when available.
- Reports now expose `product_evidence` and `stable_score` to help manual review.
## V7.1 additions
- Added simple pattern-matching examples to `rules//message_whitelist.txt`.
- Added `docs/RULE_EXAMPLES.md` to explain how those whitelist patterns work.

## V7.2 additions
- Regenerated `rules//message_whitelist.txt` from uploaded module-list content.
- Added many first-token commit-subject regex examples derived from the uploaded file.
## V7.3 additions
- Added `tools/generate_message_whitelist.py` to regenerate `rules//message_whitelist.txt` from a module-list input file.
- Documented the helper usage in `docs/RULE_EXAMPLES.md`.

## V7.4 additions
- Removed references to the previously uploaded filename and standardized examples on `modules.txt`.
## V7.5 additions
- Added `common.kbuild` for shared kernel-config and Kbuild helper functions.
- Added `common.scoring` so commit scoring logic is shared instead of duplicated in top-level scripts.
- Updated stage scripts to consume shared helpers from `common/`.
- Documented Kconfiglib as the preferred parser backend for kernel configuration handling.

## V7.7 additions
- Removed unused base config files when not needed by the curated examples.
- Reduced the example config set to a smaller relevant subset.
- Factorized common rule content into `rules/_shared/`.
- Added an internal `MANIFEST.json` for release verification.

## V7.8 additions
- Removed all `` configs, rules, and references.
- Moved profile and rule data under `configs/` and updated metadata to use relative paths.
- Added `TOOLDIR` support so the tool repository root can be separated from `WORKSPACE`.
- Updated config loading and examples to support custom configuration/profile/rule repositories.

## V7.9 additions
- Integrated report generation as the mandatory last pipeline stage.
- Added per-stage timing and pipeline progress tracking.
- Added richer report statistics and execution metadata.
- Added template-generation options to example configs.
- Added terminal progress bar support through runtime stage reporting.

## V7.10 additions
- Renamed `common/` to `lib/`.
- Moved templates under `configs/templates/`.
- Removed empty config/rule folders and stale example files.
- Removed `docs/examples/run_all.sh`.
- Made `tools/generate_message_whitelist.py --output` mandatory.
- Refreshed HTML summary rendering with embedded CSS.

## V7.11 additions
- Switched commit collection to a richer git-log format via `lib.gitutils.iter_git_log_records`.
- Integrated Kconfiglib-backed symbol loading and Kbuild-based `config_to_paths` mapping into the product map.
- Added profile-aware rule loading (`lib.profile_rules`) and rule-enhanced scoring in `lib.scoring`.
- Integrated HTML summary generation into the final reporting stage and added HTML templates under `configs/templates/`.

## V7.12 additions
- Replaced legacy shell helpers with the `kcommit_pipeline.py` Python driver for running single or all stages.
- Removed product-specific TCU profiles and examples; kept a smaller, generic ARM-embedded profile set.
- Sanitized rules and documentation to remove vendor-specific references and clarified comment support in JSON and rule files.
- Extended product scoring to use direct config-to-path mappings and added profile coverage statistics to the report.
- Added an optional `collect.max_commits` safeguard for very large revision ranges.

## V7.13 additions
- Added an initial prepare_rules stage that resolves profiles, rule categories, and compiles deduplicated rule sets for the pipeline.
- Introduced topic-based profiles (security_fixes, security_features, performance) and security rule categories (general, CVEs/bugs, memory, bounds, auth/caps, crypto/timing, syscalls).
- Added optional JSONL output for the commit collection stage and exposed collect.max_commits and collect.jsonl in example configs.
