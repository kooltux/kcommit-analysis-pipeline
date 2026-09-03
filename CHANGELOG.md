# Changelog

All notable changes to this project are documented in this file.

## v19.6.0 — feat: public configuration include mechanism with JSONC support (2026-09-03)

### Added

- **Configuration includes** — configs can now be split into ordered fragments using the top-level `include` key:
  - `"include": ["conf.d/base.json", "conf.d/extras.json"]`
  - Fragments may define their own `include` and `vars`
  - Paths resolved relative to the declaring fragment
  - `${CONFIGDIR}` supported in fragment-local vars and paths
  - Recursive includes allowed; cycles detected via active include chain
  - Shared fragments can be included through separate branches (no false-positive cycles)

- **Merge semantics**:
  - Objects: recursive union
  - Arrays: ordered union with stable canonical-JSON deduplication
  - Scalars/type conflicts: later source wins
  - Every scalar replacement and array contribution emits a warning and is recorded in `_meta.include_events`

- **Diagnostics** — composed config includes `_meta.include_events` with:
  - `scalar_replaced`: scalar overwritten
  - `array_contribution`: new elements added to array
  - Source path and old/new values for each event

- **JSONC support** — `//` line comments, `/* */` block comments, and `#` comments stripped before parsing

- **Example configuration** — `configs/example-arm-embedded-full.json` includes fragments in `configs/conf.d/`:
  - `00_vars_paths.json`, `01_kernel.json`, `02_profiles.json`, `03_filter.json`
  - `04_collect.json`, `05_history_mapping.json`, `06_reports.json`, `07_ai.json`

- **Merged output** — final composed config written to `output_dir/kcap-merged-config.json` for portability

- **Tests** — `tests/test_config_includes.py` covers:
  - Ordered includes and merge order
  - Array deduplication stability
  - Cycle detection
  - Shared fragments via separate branches
  - Fragment-local vars and CONFIGDIR resolution
  - Monolithic config compatibility

### Changed

- **lib/config.py** — `load_config()` now:
  - Accepts optional `include` key for ordered fragment composition
  - Validates unknown top-level keys only at root (fragments allow arbitrary keys)
  - Emits scalar replacement warnings during deep merge of nested objects
  - Populates `_meta.include_events` with merge diagnostics
  - Maintains backward compatibility with monolithic configs

- **lib/profile_rules.py** — uses public `load_json` instead of internal `_load_json`

- **docs/CONFIGURATION.md** — merged includes documentation section covering:
  - Overview and syntax
  - Merge semantics and examples
  - Cycle detection rules
  - Diagnostics format
  - Example configuration and test instructions

### Backward Compatibility

- Monolithic configs continue to work unchanged
- All existing config keys and behaviors preserved
- No breaking changes to API or config schema

### Tests

All 896 tests pass, including new include mechanism tests.

---

## v19.5.0 — feat: cherry-pick script as a configurable static asset + single JSON data file (2026-09-03)
