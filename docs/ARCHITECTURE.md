# Architecture notes

## Shared logic in `common/`

V7.5 moves reusable logic into `common/` modules so top-level stage scripts do not duplicate behavior.

Examples:
- `common.scoring.score_commit()` is now used by `05_score_commits.py`.
- `common.scoring.infer_touched_paths()` and `common.scoring.extract_patch_features()` are used by `04_enrich_commits.py`.
- `common.kbuild.load_kernel_config_symbols()` and `common.kbuild.scan_kbuild_makefiles()` are used by `02_collect_build_context.py`.

## Kconfiglib note

Kconfiglib is now the preferred backend for kernel configuration parsing when available. The shared `common.kbuild` helper tries to import `kconfiglib` and uses it as the preferred mechanism for kernel configuration handling, while keeping a small fallback path if the module is unavailable.

The intent for future work is to extend `common.kbuild` further so Kbuild Makefile relationships and object mappings are also derived through shared parsing utilities instead of ad-hoc stage-local code.

## V7.7 cleanup
V7.7 removes unused base configs, trims the example config set, and factorizes common rule files under `rules/_shared/`.

## V7.8 layout cleanup
V7.8 removes ``, moves rules under `configs/rules/`, and makes profile metadata reference rule content via relative paths under `configs/`.

## V7.9 pipeline runtime and reports
Report generation is now an integrated final stage of the pipeline.
A runtime state file records stage durations, statuses, and selected counters so reports can summarize what happened during execution.
