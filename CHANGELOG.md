# Changelog

All notable changes to this project are documented in this file.

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
