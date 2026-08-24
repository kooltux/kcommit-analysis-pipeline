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
  "work_dir":  "${WORKSPACE}/work",  // required: pipeline working directory
  "cache_dir": "${WORKSPACE}/work/cache",  // optional override (default: <work_dir>/cache)
  "output_dir": "${WORKSPACE}/work/output" // optional override (default: <work_dir>/output)
}
```
`work_dir` is where `cache/` and `output/` sub-directories are created.
Override `cache_dir` or `output_dir` individually to place them on different
storage (e.g. a RAM disk for the cache). Only `work_dir`, `cache_dir`, and
`output_dir` are valid under `paths` in v10.

### `kernel`
```json
"kernel": {
  "source_dir":       "${kernel_src}",              // required
  "rev_old":          "v6.1.1",                     // required
  "rev_new":          "HEAD",                        // required
  "kernel_config":    "${build_dir}/.config",        // optional but recommended
  "build_dir":        "${build_dir}",                // optional
  "kernel_build_log": "${build_dir}/kernel.log",     // optional
  "yocto_build_log":  "${build_dir}/yocto.log",      // optional
  "dts_roots":        ["${kernel_src}/arch/arm/boot/dts"],  // optional
  "arch":             "arm64",                       // optional — see note below
  "srctree":          "${kernel_src}"                // optional — see note below
}
```

#### `arch` — target architecture

When `kernel_config` is provided, stage 02 automatically detects the target
architecture from the `.config` file by scanning for `CONFIG_<ARCH>=y` markers
(e.g. `CONFIG_ARM64=y`).  Setting `arch` explicitly is therefore **not required
in most cases**.

Set `arch` explicitly only when:
- Auto-detection fails (the `.config` contains no recognised arch symbol).
- You want to override the detected value (e.g. cross-compiling with a
  non-standard config).
- You are running without a `kernel_config` but still want kconfiglib to work.

When set, the value must be the kernel `ARCH` make variable
(e.g. `"arm"`, `"arm64"`, `"x86_64"`, `"riscv"`, `"mips"`, `"powerpc"`).

The `SRCARCH` env var (the directory name under `arch/` used by the kernel
Makefile) is derived automatically from `arch`.  For the x86 family both
`x86` and `x86_64` map to `SRCARCH=x86`; for all other architectures
`SRCARCH` equals `arch`.

Explicit `kernel.arch` always takes precedence over auto-detection.

#### `srctree` — kernel source tree path for kconfiglib

kconfiglib expects a `srctree` environment variable pointing to the kernel
source root.  The pipeline sets it automatically to `source_dir` when not
provided here.  Override only when `source_dir` and the kconfiglib entry
point diverge (unusual).

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
`profiles_dirs` (defaults to `<CONFIGDIR>/profiles/`). The singular alias `profiles_dir` is also accepted for compatibility and is normalized to the same internal list form. If a requested profile is not found there, built-in fallback profiles from the tool's own `configs/profiles/` are searched automatically, and externally overridden profiles may still reference shipped built-in rule folders.

### `rules`
```json
"rules": {
  "rules_dirs": ["${CONFIGDIR}/rules"]
}
```
Rule-set directories to search (defaults to `<CONFIGDIR>/rules/`). The singular alias `rules_dir` is also accepted for compatibility and is normalized to the same internal list form. If a requested rule folder is not found there, built-in fallback rules from the tool's own `configs/rules/` are searched automatically, including when an external profile overrides a shipped profile but still relies on shipped rule folders. Legacy external names such as `artemis_generic` also fall back to shipped built-in equivalents when present.

### `filter`
Controls pre-score filtering (stage 04) and post-score filtering (stage 06).
```json
"filter": {
  "enabled":                  true,  // false = skip path/keyword rules (SHA rules always active)
  "path_blacklist_global":    true,  // drop commits where ALL touched files are blacklisted
  "require_kconfig_coverage": null,  // null=auto, true=force, false=disable
  "min_score":                0      // canonical threshold: drop commits below this score (0 = keep all)
}
```

### `history_mapping`

Controls how stage 03 builds the `CONFIG_*`-symbol → source-file history map
using `git show` on Makefiles across the revision range.

```json
"history_mapping": {
  "mode":                  "range",
  "sample_step":           500,
  "max_commits_per_probe": 3,
  "max_failure_rate":      0.05
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `mode` | `"range"` | `range` — walk rev_old..rev_new; `sampled` — every N commits; `full` — entire git history; `disabled` — skip |
| `sample_step` | `500` | Commit interval when `mode = "sampled"` |
| `max_commits_per_probe` | `3` | Maximum Makefile revisions probed per config symbol |
| `max_failure_rate` | `0.05` | Abort stage 03 if the fraction of failed `git show` calls exceeds this value |
| `history_workers` | `0` | Parallel worker count for history mapping (`0` = auto/implementation default). |

### `collect`
```json
"collect": {
  "use_numstat":         false,  // git log --numstat (adds per-line change data; enables full lines_changed/insertions/deletions size indicators)
  "count_hunks":         false,  // inspect patches of relevant (post-filter) commits to count diff hunks (stats.hunks); feeds backport_complexity. opt-in (reads patch text via git; kept set only)
  "no_merges":           true,   // git log --no-merges
  "first_parent":        false,  // git log --first-parent
  "max_commits":         0,      // cap on commits collected (0 = no limit)
  "score_workers":       0,      // parallel scoring workers (0 = auto)
  "git_binary":          "git",  // override path to git executable
  "use_name_only":       false,  // use --name-only instead of --name-status
  "extra_git_log_args":  [],     // raw extra arguments appended to git log
  "jsonl":               false,  // also write commits.jsonl for streaming consumers
  "include_parents":     false   // attach parent SHA list to each commit dict
}
```

### `reports`
```json
"reports": {
  "title":         "My Report",          // heading shown in HTML/XLSX output
  "outputs":       ["html", "csv", "xlsx"],  // formats: html, csv, xlsx, ods
  "top_n":         500,                  // max commits in reports (default: 5000; 0 = no limit)
  "templates_dir": "${CONFIGDIR}/html"   // optional: override HTML template directory
}
```

Each enabled format produces both a `relevant_commits.*` file (scored commits
above the threshold) and a `filtered_commits.*` file (commits dropped by
pre- or post-filter, with `filter_reason` column). XLSX and ODS also produce
`profile_summary.*`, `profile_matrix.*`, and a multi-sheet `summary.*`
workbook combining all views.


### `scoring` (internal)

The file `configs/scoring/subsystem_path_hints.json` maps commit metadata
keywords (subsystem tags, CVE prefixes, known authors) to kernel source-path
prefixes used to enrich product-evidence scoring. It is bundled with the
pipeline and does not normally need editing. To override or extend it, copy
the file into your product config directory and adjust the code or packaging
that loads scoring assets; there is no user-facing config key for this file.

The file is read-only from a config perspective — there is no config key
that references it directly.

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

# Force a specific architecture (overrides auto-detection)
--override '{"kernel":{"arch":"arm"}}'
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


## Cache files

- `cache/compiled_rules.json` — stage 00 compiled profile/rule patterns (deduplicated)
- `cache/prepare_summary.json` — stage 00 active profile names and rule counts
- `cache/commits.json` — stage 01 collected commits
- `cache/build_context.json` — stage 02 enabled Kconfig symbols, artifacts, and log-derived objects
- `cache/kbuild_map.json` — stage 02 static Kbuild symbol map
- `cache/product_map.json` — stage 03 combined CONFIG-to-source-path map
- `cache/prefilter_kept_commits.json` — stage 04 commits that survived prefiltering (input to stage 05)
- `cache/filtered_commits.json` — stage 04 commits dropped by prefilter
- `cache/prefilter_debug.json` — stage 04 per-dropped-commit debug detail and reason summary
- `cache/scored_commits.json` — stage 05 scored commits
- `cache/relevant_commits.json` — stage 06 commits above the score threshold
- `cache/postfilter_dropped_commits.json` — stage 06 commits dropped by the score threshold
- `cache/postfilter_debug.json` — stage 06 score distribution and threshold-drop summary
