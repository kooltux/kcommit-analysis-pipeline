# Configuration Reference

Config files are JSON with `//` and `#` comment support. All `${VAR}`
references in string values are expanded by the config loader.

Built-in variables (always available):
- `${WORKSPACE}` — from shell environment
- `${TOOLDIR}` — pipeline repository root (auto-detected)
- `${CONFIGDIR}` — directory of this config file
- `${CWD}` — current working directory

## Top-level sections

### `vars`
User-defined shorthand variables expanded before any other processing:
```json
"vars": {
  "kernel_src": "${WORKSPACE}/linux",
  "build_dir":  "${WORKSPACE}/build"
}
```

### `paths`
```json
"paths": {
  "work_dir": "${WORKSPACE}/work"
}
```
`work_dir` is where `cache/` and `output/` sub-directories are created.

### `kernel`
```json
"kernel": {
  "source_dir":       "${kernel_src}",              // required
  "rev_old":          "v6.1.1",                     // required
  "rev_new":          "HEAD",                        // required
  "kernel_config":    "${build_dir}/.config",        // optional
  "build_dir":        "${build_dir}",                // optional
  "kernel_build_log": "${build_dir}/kernel.log",     // optional
  "yocto_build_log":  "${build_dir}/yocto.log",      // optional
  "dts_roots":        ["${kernel_src}/arch/arm/boot/dts"]
}
```

### `profiles`
```json
"profiles": {
  "active": {
    "my_profile_a": 100,
    "my_profile_b": 70
  },
  "profiles_dirs": ["${CONFIGDIR}/profiles"]
}
```
`active` maps profile names to weights (0–100). Weight scales that profile's
rule contributions: 100 = full, 0 = disabled. Profiles are loaded from
`profiles_dirs` (defaults to `<CONFIGDIR>/profiles/`).

### `rules`
```json
"rules": {
  "rules_dirs": ["${CONFIGDIR}/rules"]
}
```
Rule-set directories to search (defaults to `<CONFIGDIR>/rules/`).

### `filter`
Controls pre-score filtering (stage 04) and post-score filtering (stage 06).
```json
"filter": {
  "enabled":                  true,  // false = skip path/keyword rules (SHA rules always active)
  "path_blacklist_global":    true,  // drop commits where ALL touched files are blacklisted
  "require_kconfig_coverage": null,  // null=auto, true=force, false=disable
  "min_score":                0      // drop commits below this score (0 = keep all)
}
```

### `collect`
```json
"collect": {
  "use_numstat":    false,  // git log --numstat (adds changed-lines data)
  "no_merges":      true,   // git log --no-merges
  "first_parent":   false,  // git log --first-parent
  "score_workers":  0       // parallel scoring workers (0 = auto)
}
```

### `reports`
```json
"reports": {
  "min_score":   10,    // same as filter.min_score — post-score threshold
  "top_n":       500    // maximum commits in HTML/XLSX/ODS reports
}
```

### `templates`
```json
"templates": {
  "xls_output": true,   // generate relevant_commits.xlsx
  "ods_output": false   // generate relevant_commits.ods
}
```

## `--override`

`--override` accepts a JSON object deep-merged into the loaded config.
Nested keys are merged recursively; scalar values and lists are replaced.

```bash
# Change the revision range
--override '{"kernel":{"rev_old":"v6.1.1","rev_new":"v6.6"}}'

# Disable the pre-scoring filter
--override '{"filter":{"enabled":false}}'

# Lower the score threshold
--override '{"filter":{"min_score":5}}'

# Change active profile weights
--override '{"profiles":{"active":{"my_profile_a":100,"my_profile_b":50}}}'
```

## Variable expansion

`${VAR}` is expanded in all string values. User-defined `vars` entries are
expanded first; built-in variables are always available. Self-referencing and
circular expansions are detected and raise an error.

## Directory layout (typical product config)

```
my-product/
├── config.json
├── profiles/
│   ├── my_profile_a.json
│   └── my_profile_b.json
└── rules/
    ├── rule_set_x/
    │   ├── keywords_whitelist.txt
    │   └── path_whitelist.txt
    └── rule_set_y/
        └── keywords_whitelist.txt
```
