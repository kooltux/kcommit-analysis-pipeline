# Commit exploration tool

Exploration is read-only. `check` simulates application without changing your
branches, index or files. `apply` creates real commits on a branch.
Install requirements.txt; for tests install requirements-dev.txt.
Shared options precede the command: --config, --override, --repo, --format,
--output, --progress text|jsonl|off, --verbose. Command options follow it.
Use the original config or output/pipeline_config.json. Overrides follow the
pipeline runtime semantics; --repo overrides kernel.source_dir last.

```sh
python3 kcommit_tool.py --config project.json summary
python3 kcommit_tool.py --config project.json sets
python3 kcommit_tool.py --config project.json fields
python3 kcommit_tool.py --config project.json --format raw list relevant
python3 kcommit_tool.py --config project.json show FULL_SHA --patch
python3 kcommit_tool.py --config project.json list related --where 'score >= `20`'
python3 kcommit_tool.py --config project.json list related --list manual=reviewed.txt --where 'lists.manual'
python3 kcommit_tool.py --config project.json list --commits-file candidates.txt
python3 kcommit_tool.py --config project.json validate-filter related --where 'score >= `20`' --explain --limit 10
```

JMESPath is the only expression language. Repeated --where and --filter-file
combine with AND. Each file contains one possibly multiline expression.
Predicates must return boolean or null; null excludes a record. Validation
evaluates all selected records unless --sample N is supplied. --limit only
limits explanations. Empty input leaves runtime behavior unverified.
Nested analysis fields are preserved; later valid stages take precedence.
Reserved additions sets, lists and ai never overwrite existing input fields.
sets.NAME is membership, or null for unavailable sets. Native !null is true;
compare explicitly to false when unknown must not mean non-membership.
lists.NAME is manual membership. ai is validated imported findings or null.
No AI server is needed. Displayed report rows are not analysis input.
Lists accept a hexadecimal SHA first, optional subject, and # comments.
IDs are deduplicated. Abbreviated and uncached SHAs require Git. External
candidates may lack analysis fields; no score is invented. Fields default
to all; list and validation default to related. --project transforms output;
--sort accepts uniform strings/numbers, with nulls last. Display sorting
does not determine execution order. The legacy standalone helper is retained.
Formats: text, raw, CSV, JSON, Markdown. Raw normally emits commit IDs.
Nested table values use JSON. Progress/errors use stderr. Reports are
output-only; existing destination files are never overwritten.
Exit codes: 0 success, 1 data/I/O/Git error, 2 CLI/filter error.

## Checking application

```sh
python3 kcommit_tool.py --config project.json check relevant --where 'score >= `20`' --target product
python3 kcommit_tool.py --config project.json check --mode individual --method cherry-pick
python3 kcommit_tool.py --config project.json check --dry-run
```

Selection, lists and `--where` work as in `list`. Options: `--target REV`
(default `kernel.rev_old`, shown resolved to a full SHA), `--mode series|individual`
(default series: successful commits accumulate; individual: each starts from the
target), `--method index|cherry-pick` (default index), `--on-conflict skip|stop`
(default skip), `--dry-run` (resolve and preview only).

Only selected commits are tested, ancestor-first regardless of input or display
order. Commits already contained in the target are flagged `in_target`. Merge
commits are `unsupported` (no mainline policy); objects that are missing or not
commits are `error` rows that do not stop other work.

Methods: `index` applies each patch (binary-safe, three-way) to a private
temporary index. `cherry-pick` runs one real cherry-pick per commit in a
disposable detached worktree with hooks, signing and rerere disabled; it adds
and removes temporary worktree metadata in the repository's Git directory. It is
slower. Neither changes your branches, index or working files; the index method
is a patch-application estimate and may differ from real cherry-picks.

Outcomes: `clean`, `no_change` (empty or no tree change), `conflict`,
`unsupported`, `error`, `not_tested`. Each row has position, conflicting paths
and `conflict_count` (null when Git cannot tell, never a guessed zero), the Git
diagnostic, `recovery` (`verified`, `reset`, `failed`, `not_needed`) and tree IDs
before/after. A failed attempt is rolled back and verified before the next one;
an operational error or failed recovery stops the run (`execution_complete`
false, exit 1). `--on-conflict stop` leaves later commits `not_tested`.

A commit that conflicts individually can succeed in series, and a skipped
conflict is not applied, so later series results exclude it. `--sort`,
`--limit` and `--project` shape the report only, never the execution. Result
rows are compact (commit, subject and check fields, not full analysis records);
use `list` or `show` for those. `--format raw|csv|markdown` render result rows,
`json` the whole report, `text` a summary. Conflicts are results, so exit status
is 0 unless execution fails (1) or is interrupted (130); temporary state is
removed on interruption.

## Applying commits

```sh
python3 kcommit_tool.py --config project.json apply relevant --new-branch backport/net --target product
python3 kcommit_tool.py --config project.json apply --list manual=picks.txt --where 'lists.manual' --branch backport/net
python3 kcommit_tool.py --config project.json apply relevant --new-branch x --dry-run
```

Selection works as in `check`. The destination is exactly one of `--new-branch NAME`
(created at `--target`, default `kernel.rev_old`) or `--branch NAME` (extended from
its current tip; `--target` is rejected). Existing or checked-out branches and
invalid names are refused; a branch checked out in any worktree must be switched
away first. `apply` needs a configured Git committer identity.

Commits are cherry-picked one at a time, ancestor-first, in a disposable detached
worktree, so your checkout, index, `HEAD` and files are never touched. Git
identity and signing settings are yours; hooks are disabled. Authors are kept.
The `(cherry picked from commit ...)` trailer is added unless
`--no-record-origin`. Merge commits are `unsupported`.

The branch moves only at the end, in one compare-and-swap `update-ref` against the
tip observed at the start. If the branch changed meanwhile, nothing is published
and the report says so. Interruption or an operational error publishes nothing.

Policies: `--on-conflict stop|skip` (default stop; a conflict is aborted and the
tree verified clean first). `--publish complete|applied` (default complete): move
the branch only if every selected commit applied (or needed no change), or keep
whatever applied. Outcomes: `applied` (with `new_commit`), `no_change`,
`conflict`, `unsupported`, `error`, `not_tested`. The report also has the
destination (`base`, `old_tip`), `published`, `state`, `reason` and `new_tip`.

Exit status: 0 published, dry run or nothing to do; 3 not published because the
publish policy was not met; 1 failure (including a branch that moved); 130
interrupted. `check` first to estimate effort; `apply` does not require it.

## Verification

Run `python3 -m pytest tests/test_kcommit_tool.py tests/test_tool_check.py tests/test_tool_apply.py tests/test_kcommit_tool_check.py tests/test_kcommit_tool_apply.py tests/test_commit_sets.py`,
then `./run_tests`. Full QA is required before committing. No version bump or
commit is implied.
