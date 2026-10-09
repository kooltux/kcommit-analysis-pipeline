# Resource isolation and migration

## Resolution contract

The directory of the initial configuration file is the immutable anchor for all
relative includes and registered resource paths, including values in nested
fragments. Neither the fragment directory nor the calling directory replaces it.
`CONFIGDIR` defaults to this directory; an explicit variable override can select
resources but does not move the anchor. `TOOLDIR` defaults to the tool installation.
A built-in declaration such as `"WORKSPACE": "${WORKSPACE}"` retains its incoming
value. Referenced empty built-ins fail before they become unintended root paths.

Runtime loading and manifest export share one merged snapshot. Runtime metadata
records `initial_config_path`, `initial_config_dir`, `loaded_files`, and include
events. Manifest export preserves intermediate variable references and omits
runtime metadata. Explicit resource selections resolve consistently in both.

## Resource selection

| Configuration key | Default under the initial directory |
| --- | --- |
| `profiles.profiles_dirs` | `profiles/` |
| `rules.rules_dirs` | `rules/` |
| `scoring.scoring_dir` | `scoring/` |
| `reports.templates_dir` | `html/` |
| `paths.assets_dir` | `assets/` |
| `ai.prompt_path` | `ai/ai_analysis_prompt.md` |
| `ai.front_page_path` | `ai/ai_server_front_page.md` |
| `ai.result_schema_path` | `ai/ai_analysis_result_schema.json` |

Directory keys for profiles/rules accept multiple roots; names must be unique
across selected roots. Sample directories are not an automatic secondary tier.
The loader derives consumer paths such as `paths.templates_dir` from user-facing
sections; configure `reports.templates_dir`, not a fabricated derived-path key.

Required profile/rule sources, HTML templates, cherry-pick script assets, and
Stage 08 AI inputs must exist when their consuming feature runs. Scoring hints,
helper scripts, and the legacy Stage 07 prompt remain optional. A missing optional
file does not cause the tool to import a sample file instead.

## Migrating existing configurations

1. Identify resources previously supplied by automatic sample fallback.
2. Copy product resources beside the initial configuration, or declare their
   directories/file paths explicitly. Relative values use the initial anchor.
3. To intentionally reuse samples, select `${TOOLDIR}/configs/...` explicitly:

```json
{
  "profiles": {"profiles_dirs": ["${TOOLDIR}/configs/profiles"]},
  "rules": {"rules_dirs": ["${TOOLDIR}/configs/rules"]},
  "scoring": {"scoring_dir": "${TOOLDIR}/configs/scoring"},
  "reports": {"templates_dir": "${TOOLDIR}/configs/html"},
  "paths": {"assets_dir": "${TOOLDIR}/configs/assets"},
  "ai": {
    "prompt_path": "${TOOLDIR}/configs/ai/ai_analysis_prompt.md",
    "front_page_path": "${TOOLDIR}/configs/ai/ai_server_front_page.md",
    "result_schema_path": "${TOOLDIR}/configs/ai/ai_analysis_result_schema.json",
    "chunk_size": 100
  }
}
```

This fragment selects resources; it is not a complete kernel/product configuration.
Do not mix product and sample roots containing the same profile/rule names and
expect precedence. Select one implementation, or rename the product entries.
Stage 08 `--ai` requires a positive integer chunk size; zero is not supported.

## Relocating the full example

Copy `configs/example-arm-embedded-full.json` and its `conf.d/` directory together.
The example explicitly selects sample resources through `TOOLDIR`, so resources
remain usable without copying the installed resource trees beside the new config.
Set `WORKSPACE` to the intended product workspace; adapt kernel/build inputs before
a real pipeline run. Replace sample selections when using product-owned resources.

Nested includes still use the initial directory, even when an intermediate entry
fragment lives in another directory. Cache validation uses the selected roots,
active profile identities, and referenced source files; an unverifiable live
source forces recompilation/error rather than blind reuse of a compiled cache.

## QA

Run `./run_tests` from the repository root. The relocated-example integration test
checks nested provenance, runtime/export resource agreement, real sample-rule
compilation, and Stage 08 packaging from test-local empty commit caches. It does
not replace validation of real kernel/build inputs or a production pipeline run.
