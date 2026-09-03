# Changelog

All notable changes to this project are documented in this file.

## v19.5.0 — feat: cherry-pick script as a configurable static asset + single JSON data file (2026-09-03)

### BREAKING

Cherry-pick execution now uses a single `cherry_pick.sh` script with a `--set`
argument, plus a `cherry_pick_data.json` data file, instead of separate
`cherry_pick_prefiltered.sh` and `cherry_pick_relevant.sh` scripts.

**Old workflow:**
```bash
./cherry_pick_relevant.sh    # apply relevant commits
./cherry_pick_prefiltered.sh # apply all prefilter commits
```

**New workflow:**
```bash
./cherry_pick.sh --set=relevant      # apply relevant commits
./cherry_pick.sh --set=prefiltered   # apply all prefilter commits
./cherry_pick.sh --help              # commit counts computed live from data file
```

### Added

- **configs/assets/cherry_pick.sh** — new static asset directory holding files
  that are copied verbatim into `output/` rather than generated. The
  cherry-pick script is the first resident: a fully generic, run-independent
  bash script with:
  - `usage()` function, automatically invoked on `-h`/`--help`, a missing or
    invalid `--set` value, and any unrecognized option -- no need to pass
    `-h` explicitly to see help on a usage error.
  - `getopt`-based option parsing for robust, standards-compliant argument
    handling (long options, `--`, combined short options, etc.).
  - Commit counts in the help text (`Total`, `Relevant`, `Prefiltered-only`)
    computed **live** from `cherry_pick_data.json` at run time -- never
    hardcoded, never stale.
  - Small Python snippets embedded via `python3 - <<'PYEOF' ... PYEOF`
    heredocs with a **quoted** delimiter, so bash performs no expansion or
    reinterpretation inside them; the data-file path and other values are
    passed as real `sys.argv` entries instead of being interpolated into the
    Python source text. This lets Python be embedded directly in the bash
    script (no companion helper file) while completely avoiding
    bash/Python nested-quoting corruption -- verified end-to-end with commit
    subjects containing parentheses and both quote styles.
  - `cp_one()` wrapper printing colorized per-commit progress and logging
    failures to `cherry_pick.log` (carried over from v19.4.2, now part of
    the static asset).
  - Branch-creation prompt (`cherrypicking_from_<rev_new>`) before starting.

- **`paths.assets_dir` config key** — new entry in the canonical `paths`
  namespace (alongside `work_dir`, `cache_dir`, `output_dir`), resolved with
  the same default/override convention already used by `reports.templates_dir`
  and `scoring.scoring_dir`: defaults to the pipeline's own
  `configs/assets/`, and accepts an absolute or `${CONFIGDIR}`-relative
  override in a product config (e.g. `"paths": {"assets_dir": "${CONFIGDIR}/assets"}`).
  Lets a product config ship its own customized `cherry_pick.sh` (e.g. with
  extra pre/post hooks) without forking the pipeline.

- **Testing section in README.md** — documentation on running the test suite:
  - Using the `run_tests` script (recommended)
  - Manual pytest invocation with `WORKSPACE` variable
  - Test structure overview with file-to-coverage mapping
  - Test fixtures and continuous integration notes

### Changed

- **lib/config.py** — added `assets_dir` to `CONFIG_SCHEMA['paths']` and to
  the canonical `paths` namespace populated by `load_config()`; resolution
  mirrors `templates_dir` exactly (default from the tool's own `configs/`
  tree, override read from the already-path-resolved `paths` dict, relative
  values re-resolved against `config_dir` defensively).

- **lib/cherrypick_script_gen.py** — complete rewrite to v19.5.0 design:
  - `write_cherry_pick_files()` now **copies** `cherry_pick.sh` byte-for-byte
    from `cfg['paths']['assets_dir']` into `output/cherry_pick.sh` (then
    `chmod +x`) instead of assembling it from hundreds of string-joined
    lines in Python. Falls back to the shipped `configs/assets/` default
    when `cfg['paths']` is absent or incomplete (e.g. hand-built cfg dicts
    in unit tests).
  - Only `cherry_pick_data.json` is generated; it embeds `target_rev` and
    `rev_new` alongside the ordered commit list so the script is fully
    self-contained.
  - Removed all in-Python script-text generation (`_build_cherry_pick_script`)
    and the short-lived companion-helper-script approach explored mid-session
    (`_HELPER_PY` / `cherry_pick_helper.py`) -- neither is needed once Python
    is embedded correctly via quoted heredocs.

- **lib/stages/st07_report.py** — updated to call the new `write_cherry_pick_files()` API.

- **tests/test_config.py** — added coverage for `paths.assets_dir`: default
  resolution to the shipped `configs/assets/`, absolute override, and
  `${CONFIGDIR}`-relative override resolution.

- **tests/test_cherrypick_script_gen.py** — rewritten for the copy-based design:
  - Asserts `output/cherry_pick.sh` is byte-identical to the resolved asset.
  - Validates the static asset with `bash -n`.
  - Adds real subprocess-level end-to-end tests: `--help`, no-args, invalid
    `--set`, and a full `git cherry-pick` run against a real temporary repo
    with a commit subject containing parentheses and mixed quotes.
  - Adds `paths.assets_dir` override coverage: default resolution, explicit
    override, and an end-to-end run confirming the overridden script (not
    the shipped default) is the one actually copied.

- **tests/test_st07_report.py** — integration tests check for `cherry_pick.sh`
  + `cherry_pick_data.json` (unchanged from the prior draft; still valid
  under the copy-based design).

- **run_tests** — added `export WORKSPACE=$(pwd)` for pytest compatibility.

- **MANIFEST.json** — updated outputs to reflect `cherry_pick.sh` +
  `cherry_pick_data.json`.

- **README.md** / **docs/CONFIGURATION.md** — rewrote the "Cherry-pick
  execution scripts" section to describe the static-asset-copy mechanism,
  the `paths.assets_dir` override, and the quoted-heredoc technique; added
  Testing section to README.md.

### Rationale

- A copied static script is easier to review, diff, and shellcheck than one
  assembled from generated string joins.
- `configs/assets/` cleanly separates "files copied verbatim into output/"
  from templated/generated config (profiles, rules, HTML templates).
- Resolving the asset through `paths.assets_dir` (same convention as
  `templates_dir`/`scoring_dir`) lets product configs customize or replace
  the script without touching the pipeline's own tree.
- Single source of truth for commit order (no duplication between two files).
- Boolean `relevant` flag is simpler than maintaining two separate arrays.
- `output/` folder can be exported/archived independently from `cache/`.
- Quoted heredocs + `sys.argv` let Python live directly inside the bash
  script with zero quoting fragility, without introducing a second file to
  maintain and ship alongside the script.

### Tests

All tests pass, including new end-to-end subprocess tests that execute the
copied script against a real git repository, and new `paths.assets_dir`
default/override coverage in both `lib.config` and `lib.cherrypick_script_gen`.

---

## v19.4.2 — feat: enhanced cherry-pick scripts with progress, logging, and branch prompt (2026-09-02)

### Added

- **Progress output in generated scripts** — each `git cherry-pick` call is now
  wrapped in a `cp_one()` bash function that prints:
  - `Commit <SHA> <n>/<max> - OK` in green on success
  - `Commit <SHA> <n>/<max> - FAIL` in red on failure (to stderr)

- **Centralized failure logging** — each script writes all failures to a single
  log file (`cherry_pick_prefiltered.log` or `cherry_pick_relevant.log`), with
  clear separators and full error output for each failing commit. The log file
  is recreated fresh on each run.

- **Branch creation prompt** — before starting, the script prompts:
  `Create local branch cherrypicking_from_<rev_new> before starting? [y/N]`
  If accepted, creates and switches to that branch; otherwise continues on the
  current branch.

### Changed

- **lib/cherrypick_script_gen.py** — replaced raw `git cherry-pick <sha>` lines
  with calls to a new `cp_one()` wrapper function that implements the progress
  output, colorization, and logging behavior described above.

- **tests/test_cherrypick_script_gen.py** — updated all script-content tests to
  expect `cp_one "<sha>"` calls instead of raw `git cherry-pick`, and added new
  tests verifying the presence of `LOGFILE=`, color codes (`GREEN=`, `RED=`,
  `NC=`), the branch prompt (`BRANCH_NAME=`, `read -p`, `git checkout -b`), and
  the progress format strings.

### Configuration

No config changes — purely an enhancement to the generated scripts' UX.

---

## v19.4.0 — feat: cherry-pick execution scripts generated at report stage (2026-09-02)

