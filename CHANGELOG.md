# Changelog

All notable changes to this project are documented in this file.

## v19.8.0 — feat: portable helper scripts for output archives (2026-09-04)

### Added

- **configs/assets/json_query.sh** — Self-contained JSON query tool:
  - Query JSON files using dotted notation (e.g., `kernel.rev_old`)
  - Returns scalars as plain text, objects/arrays as compact JSON
  - Determines its own location — works when copied anywhere
  - Used by archive_output.sh and for manual queries

- **configs/assets/archive_output.sh** — Automated archive creation:
  - Extracts `kernel.rev_old` and `kernel.rev_new` from config
  - Creates timestamped archives: `kernel_commit_analysis_<old>_<new>_<YYYYMMDD>.tar.gz`
  - Self-contained — uses json_query.sh from same directory
  - Supports WORKSPACE env variable or script directory

- **lib/stages/st07_report.py** — `_copy_helper_scripts()` function:
  - Copies scripts to `output/scripts/` subdirectory at end of stage 07
  - Makes scripts executable (0o755)
  - Scripts are portable with the output directory

### Organization

Scripts are placed in `output/scripts/` subdirectory:
```
output/
  scripts/
    json_query.sh
    archive_output.sh
  pipeline_config.json
  summary.html
  ...
```

### Usage

```bash
# From output/ directory:
cd output/
./scripts/archive_output.sh              # Uses pipeline_config.json
./scripts/archive_output.sh config.json  # Or specify config

# Query config:
./scripts/json_query.sh pipeline_config.json kernel.rev_old
```

### Benefits

- **Portability** — output/ directory is self-contained with archive capability
- **Convenience** — One command to create properly-named archives
- **Flexibility** — json_query.sh reusable for any JSON queries

### Backward Compatibility

- No breaking changes
- Scripts are optional additions to output/
- Existing pipeline runs unaffected

---

## v19.7.0 — feat: pipeline_config.json manifest preserves non-expanded variables (2026-09-04)

### Added

- **lib/config.py** — New function `load_config_with_raw()` returns both expanded and raw (non-expanded) config versions:
  - `expanded`: Fully processed config with variable expansion and path resolution (existing behavior)
  - `raw`: Merged config with original variable references preserved (e.g., `${WORKSPACE}/work`)
  
- **lib/config.py** — New internal function `_build_raw_merged_config()` builds the raw merged config:
  - Includes are merged
  - `vars` section kept as-is (no expansion)
  - Paths not resolved to absolute paths
  - No `_meta` or `config_dir` added

- **tests/test_config_raw_manifest.py** — New test suite for raw config manifest generation:
  - `test_load_config_with_raw_returns_both_versions` — verifies both configs are returned
  - `test_raw_config_preserves_variables_with_includes` — tests includes with variables
  - `test_build_raw_merged_config_standalone` — tests the standalone function
  - `test_manifest_would_contain_variable_references` — documents expected manifest behavior
  - `test_raw_config_with_array_merges` — verifies array merges work in raw config

### Changed

- **lib/stages/st07_report.py** — `_dump_merged_config()` now accepts `raw_cfg` parameter:
  - Uses raw (non-expanded) config for manifest generation
  - Preserves variable references like `${WORKSPACE}/work` in `output/pipeline_config.json`
  - Makes manifests more portable and reproducible across different environments
  
- **lib/stages/st07_report.py** — `run()` function updated to load raw config:
  - Calls `load_config_with_raw()` when config path is available
  - Falls back to expanded config if raw loading fails
  - Passes raw config to `_dump_merged_config()`

- **lib/stages/st07_report.py** — Module docstring updated to document v19.7.0 change

### Benefits

- **Portability** — Manifests can be reused across different environments without hardcoded absolute paths
- **Reproducibility** — Variable references show the intended configuration structure
- **Debugging** — Easier to understand config relationships when variables are visible

### Backward Compatibility

- Existing `load_config()` function unchanged — full backward compatibility
- Pipeline behavior unchanged — only manifest output format differs
- All existing configs work without modification

### Tests

New test file `tests/test_config_raw_manifest.py` with 6 test cases covering raw config generation.

---

## v19.6.1 — fix: filter internal metadata from pipeline_config.json manifest (2026-09-03)

### Fixed

- **lib/stages/st07_report.py** — `_dump_merged_config()` now filters out internal metadata before writing:
  - `_meta` section (internal diagnostics: config_path, config_dir, vars, include_events)
  - Standalone `config_dir` key (redundant; already in `paths` and `_meta`)
  - Only user-facing configuration keys are written to `output/pipeline_config.json`

### Changed

- **lib/stages/st07_report.py** — updated docstring to document the filtering behavior

### Tests

All 896 tests pass.

---

## v19.6.0 — feat: public configuration include mechanism with JSONC support (2026-09-03)
