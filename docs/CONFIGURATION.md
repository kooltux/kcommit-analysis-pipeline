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
User-defined shorthand variables:
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
  "source_dir":       "${kernel_src}",         // required
  "rev_old":          "v4.14.206",             // required
  "rev_new":          "v4.14.336",             // required
  "kernel_config":    "${build_dir}/.config",  // optional
  "build_dir":        "${build_dir}",          // optional
  "kernel_build_log": "${build_dir}/kernel.log",  // optional
  "yocto_build_log":  "${build_dir}/yocto.log",   // optional
  "dts_roots":        ["${kernel_src}/arch/arm/boot/dts"]
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
`active` maps profile names to weights (0–100). Weight scales rule
contributions: 100 = full, 0 = disabled. Profiles are loaded from
`<CONFIGDIR>/profiles/` by default (override with `"profiles_dir"`).

### `filter`
Controls both pre-score filtering (stage 04) and post-score filtering (stage 06).
```json
"filter": {
  "enabled":                true,   // false = skip path/keyword rules (SHA rules always on)
  "path_blacklist_global":  true,   // drop commits where ALL touched files are blacklisted
  "require_kconfig_coverage": null, // null=auto, true=force, false=disable
  "min_score":              0       // drop commits below this score (0 = keep all)
}
```

### `collect`
```json
"collect": {
  "use_numstat":      true,   // attach per-file change stats
  "use_no_merges":    true,   // pass --no-merges to git log
  "use_first_parent": false,  // pass --first-parent to git log
  "max_commits":      0,      // 0 = no limit
  "score_workers":    0,      // parallel scoring workers (0 = auto)
  "jsonl":            false,  // also write 01_commits.jsonl
  "include_parents":  false   // attach parent SHA list to commits
}
```

### `history_mapping`
Controls how the CONFIG_* → source-file map is enriched via git history:
```json
"history_mapping": {
  "mode":                  "sampled",  // range | sampled | full | disabled
  "sample_step":           500,        // used when mode = sampled
  "max_commits_per_probe": 3,
  "max_failure_rate":      0.05
}
```

### `templates`
Output format flags and HTML options:
```json
"templates": {
  "html_summary":  true,
  "report_title":  "My Product Analysis",
  "top_n":         5000,
  "css_override":  "",       // path to extra CSS appended after built-in styles
  "csv_output":    true,
  "xls_output":    true,
  "ods_output":    true
}
```

## Runtime overrides

Any config key can be overridden without editing the file:
```bash
python3 kcommit_pipeline.py --config cfg.json \
    --override '{"kernel":{"rev_old":"v4.14.111"},"filter":{"min_score":15}}'
```
The JSON object is deep-merged: nested dicts are merged recursively; scalars
and lists are replaced. The override is forwarded to every stage script.
