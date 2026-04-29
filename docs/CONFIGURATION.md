# Configuration Reference

Configuration files are JSON with `//` and `#` comment support (stripped
before parsing). All `${VAR}` references in string values are expanded by the
config loader.

## Top-level sections

### `vars`

User-defined shorthand variables for use elsewhere in the file.
Environment variables can be captured here:

```json
"vars": {
  "WORKSPACE": "${WORKSPACE}",
  "kernel_src": "${WORKSPACE}/linux"
}
```

Built-in variables (always available, no need to declare):
- `${WORKSPACE}` — from shell environment
- `${TOOLDIR}` — pipeline repository root (auto-detected)
- `${CONFIGDIR}` — directory of this config file
- `${CWD}` — current working directory

### `project`

```json
"project": {
  "name":     "my-product",
  "work_dir": "${WORKSPACE}/work"
}
```

`work_dir` is where `cache/` and `output/` sub-directories are created.

### `kernel`

```json
"kernel": {
  "source_dir":       "${kernel_src}",    // required: git repo path
  "rev_old":          "v4.14.206",        // required: start revision
  "rev_new":          "v4.14.336",        // required: end revision
  "kernel_config":    "${build_dir}/.config",    // optional
  "build_dir":        "${WORKSPACE}/build",      // optional
  "kernel_build_log": "${logs_dir}/kernel_build.log",  // optional
  "yocto_build_log":  "${logs_dir}/yocto_build.log",   // optional
  "dts_roots":        ["${kernel_src}/arch/arm/boot/dts"]  // optional
}
```

### `profiles`

```json
"profiles": {
  "active": {
    "security_fixes":    100,
    "security_features":  90,
    "performance":        70
  }
}
```

`active` is a map of `profile-name → weight (0–100)`. List form also accepted.
The weight scales each profile's rule contributions (100 = full, 0 = disabled).

Profiles are loaded from `<CONFIGDIR>/profiles/` by default.
Override with `"profiles_dir": "/path/to/profiles"`.

### `filter` *(v8.6)*

Controls the pre-scoring filter in stage 04. All keys are optional.

```json
"filter": {
  "enabled":              true,   // false = skip rules 2+3 (rule 1 always active)
  "path_blacklist_global": true,  // drop commits where ALL paths are blacklisted
  "require_product_map":  false   // drop commits with no product-map coverage (opt-in)
}
```

See `docs/ARCHITECTURE.md → Pre-scoring filter` for rule details.

### `collect`

```json
"collect": {
  "use_numstat":      true,   // attach file-change stats
  "use_no_merges":    true,   // --no-merges to git log
  "use_first_parent": false,  // --first-parent to git log
  "max_commits":      0,      // 0 = no limit
  "score_workers":    4,      // parallel workers in stage 05 (0 = all CPUs)
  "jsonl":            false,  // also write commits.jsonl
  "include_parents":  false   // attach parent SHA list to each commit
}
```

### `history_mapping`

```json
"history_mapping": {
  "mode":                  "sampled",  // range | sampled | full | disabled
  "sample_step":           500,
  "max_commits_per_probe": 3,
  "max_failure_rate":      0.05
}
```

### `scoring` *(v8.6)*

This section is reserved for future non-profile scoring extensions.
The previous v8.4/v8.5 multipliers (`product`, `security`, `performance`,
`stable`, `symbol_match`) are **no longer used** — scoring is exclusively
through profiles and rules. Remove these keys from your config.

### `templates`

```json
"templates": {
  "html_summary":  true,
  "report_title":  "My Product Analysis",
  "top_n":         500,
  "css_override":  "${CONFIGDIR}/templates/custom.css",
  "csv_output":    true,
  "xls_output":    false,
  "ods_output":    false
}
```

`css_override` (replaces deprecated `summary_css`) is a path to a CSS file
appended after the built-in styles. Relative paths resolve from `CONFIGDIR`.

## `--override` runtime overrides

Any config key can be overridden at runtime without editing the config file:

```bash
python3 kcommit_pipeline.py --config cfg.json \
    --override '{"kernel":{"rev_old":"v4.14.111"}}'
```

The JSON object is **deep-merged** into the loaded config: nested dicts are
merged recursively; scalars and lists are replaced; unpatched sibling keys
are preserved.

The override is forwarded to every stage script automatically.
