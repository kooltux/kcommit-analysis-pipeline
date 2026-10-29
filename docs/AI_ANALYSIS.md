# Optional AI analysis workflow

## Directory-only integration

Validation and Stage 08 use `load_contract(cfg)` to snapshot `ai.prompts_dir` and
`ai.schemas_dir`. Defaults are `ai/prompts` and `ai/schemas` under the initial
configuration directory; installed samples require explicit TOOLDIR selection.
The old `prompt_path` and `result_schema_path` keys are removed.

Stage 08 calls `build_package` with Stage 04 prefilter-kept commits and the Stage 03
product map, then `generate_ai_package_server` with the exact snapshots and guide.
All selected prompt/schema bytes affect identity; deterministic scores do not.
The complete package and zipapp are prepared before live assets are replaced.
Validation/generation failures preserve existing outputs. Publication is per-file/
per-tree replacement, not a transaction across filesystem failures.

`lib.ai_workflow` validators are embedded in the portable server for role and
assembly HTTP gates. Final-result upload alone does not enforce the role chain.

## Directory-contract portable server

`lib.ai_package_server.generate_ai_package_server` consumes the new in-memory
package, verifies contract/root/source checksums and atomically publishes a zipapp.
Its `/contract`, `/prompt/<name>`, `/schema/<name>` and `/metadata/<name>` routes
provide exact assets and trusted identity fields through the executable registry.
The zipapp has no repository or third-party runtime imports. Stage 08 selects
this entry point, including the validation-only POST gates described below.

## Directory-package construction engine

`lib.ai_preparation.build_package` builds chunks and manifest/file snapshots in
memory from the selected contract. It uses exact selected schema bytes, enforces
input constraints, checks global SHA uniqueness and hashes every prompt/schema
into run identity. It performs no output writes. Stage 08 publishes its returned
files, including the complete `ai_contract/` tree, and embeds them in the server.

## Forward-only contract tests

The review-runtime, CSV-review and server-contract tests select only
`configs/ai/schemas/result.json`. Review cases always execute; old-schema fixture
combinations and their skip branches have been removed. Ordinary non-nullable
array/string cell semantics remain tested because they are part of the current
contract too. Stage 08 integration tests exercise directory configuration.

## AI package ownership

Stage 08 alone creates AI inputs, prompt/schema snapshots and the portable server.
Stage 07 and import-driven report refreshes leave existing AI package bytes alone,
including packages awaiting remote analysis. Report regeneration does not require
prompt/schema resources or rerun analysis. The obsolete Stage 07 single-file/flat
chunk generator and its import-wrapper workaround have been removed. This does
not change scoring. Import verifies every packaged contract asset checksum.

## Runtime schema correctness checks

Install `requirements.txt` before running the pipeline; tests use `requirements-dev.txt`.
`validate`, Stage 00 and lightweight stage preflight check all five bundled schemas,
even when AI is disabled. Missing or invalid bundled files are blocking errors.
Active AI checks the selected directory contract. Independent Stage 08 repeats
bundle and selected-asset checks before reading caches or replacing outputs.
Input chunks use the exact selected `schemas/input.json`, not a generated schema.
Checks use the Draft 2020-12 meta-schema and require the canonical dialect URI when
`$schema` is present; legacy schemas without it default to that dialect.
Local pointers and anchors must resolve to schemas. External references, nested
`$id` resources, duplicate anchors/JSON keys and non-JSON constants are rejected.
These checks are offline and report file/schema locations. They do not replace
payload validation, source identity, coverage or cross-document preservation gates.
Role serving, directory packaging and remote role/workflow validation gates are active.

## Explicit role schema assets

`configs/ai/schemas/` contains self-contained Draft 2020-12 contracts:
`input.json`, `analyst.json`, `cve.json`, `reviewer.json` and `result.json`.
The input asset initially preserves the generated input contract. Analyst, CVE
and Reviewer documents require their role identity; final results have no role
field and require all 18 assessment fields. Agree requires null review arrays;
disagree requires nonempty, ASCII-formatted arrays naming known assessment fields.
`output_schema_checksum` identifies the shared final result schema for all roles.
Runtime packaging, role discovery and HTTP validation use these selected assets.

## Multi-role prompt preparation

Basic role prompts are in `configs/ai/prompts/`: Analyst (`analyst.md`), CVE
expert (`cve.md`), Reviewer (`reviewer.md`) and Assembler (`assembler.md`).
The Reviewer emits only review fields; the Assembler preserves the validated
specialist and review values in the final document without applying corrections.
The obsolete single-prompt and result-schema configuration files have been removed;
use the selected `prompts/` and `schemas/` directories. Generated package snapshots
retain their existing filenames and checksums for package/import validation;
they are derived from the selected assets, not the removed configuration files.
Each role prompt directly instructs the model to return one JSON document matching
its supplied output schema: Analyst uses `analyst.json`, CVE uses `cve.json`,
Reviewer uses `reviewer.json`, and Assembler uses `result.json`. Supply the relevant
input and output schemas as attachments or quoted content after the prompt.
Intermediate outputs must not use the final-result schema. A missing, unreadable
or conflicting required schema stops the task instead of producing guessed JSON.

The legacy assessment policy is distributed by responsibility, not discarded:

| Policy | Owner |
| --- | --- |
| Prefilter-kept inputs, independent product assessment, evidence and uncertainty | Analyst |
| Explicit mitigation safeguards, concise rationales, effort beyond line counts | Analyst; Reviewer checks |
| Source-message-only CVEs, empty unsupported matches, aligned integer percentages | CVE expert; Reviewer checks |
| Preserve source metadata, scores, rankings and cherry-pickability | Analyst and Reviewer |
| Risk `none` alone, advisory decisions and `maybe` for insufficient evidence | Analyst |
| Trusted identities, full SHA joins, exact value preservation and coverage | All roles; Assembler joins |
| Batch selection, pagination, POST/GET verification and export | Shared server guide; workflow orchestration |

Stage 08 packages every selected prompt and serves `/prompt/<name>`.
`/contract` lists assets; the bare prompt URL is removed. Do not upload specialist
intermediate JSON to the final-result endpoint.
The new prompt loader snapshots immediate `*.md` files, dereferencing directory
and file symlinks, validating UTF-8 and preserving entry filenames and exact bytes.

## Remote validation gates

POST each Analyst, CVE and Reviewer document to `/validate/role/<role>/<name>`.
`role` is `analyst`, `cve` or `reviewer`; `name` is the manifest-listed chunk path,
such as `batch_001/001.json`. A role gate checks that document's identity, source
membership, counts and fields; it does not cross-check specialist contributions.

After assembly, POST an object with exactly `analyst`, `cve`, `reviewer` and
`result` documents to `/validate/workflow/<name>`. It validates every document,
requires reviewer coverage to have both specialist contributions, and requires
final coverage to be reviewed. Final values must equal the combined contributions;
recommendations remain advisory and are never applied. Partial coverage is allowed
when the individual statuses/counts and cross-document subset relations are valid.

Both endpoints return HTTP 200 with `status: valid`, trusted `run_id` and
`source_chunk`; malformed JSON, identities, fields or assembly return 400. Unknown
roles/chunks return 404. Normal authentication and access logging apply. Bodies
must be UTF-8 JSON, 1 byte to 10 MiB with one Content-Length and no Transfer-Encoding.
Duplicate JSON keys and non-JSON constants are rejected. `/api` lists effective
limits and role contracts from the executable registry. Validation uses archived
source bytes, manifest checksums and packaged schemas, never supplied context.

These are validation-only operations: they neither create nor replace stored
results and return no reusable validation ticket. Submit the unchanged validated
`result` separately to `/result/<name>`. That endpoint remains available for manual
CSV results and does not itself enforce the multi-role chain. Keep the package
unchanged during delayed remote analysis/import; no history database is introduced.

## Convert manual CSV assessments

Use the original run's generated configuration; the converter reads its resolved
output directory, original manifest, exact source chunks and generated schemas.
It does not rerun Stage 08, import assessments or regenerate reports.

```sh
python3 tools/ai_csv_to_results.py --config output/pipeline_config.json \
  --output-dir converted-results --rationale-from-summary manual-results/
python3 kcommit_pipeline.py ai-import --config output/pipeline_config.json \
  --results-bundle converted-results/
```

Inputs may be CSV files or recursively scanned batch directories. `commit_hash`
is authoritative; CSV filenames and folder names do not determine identity.
Output uses the original `batch_NNN/NNN.json` paths and server-compatible result
envelopes, including original identities, exact-byte checksums and complete or
partial status. Chunks without assessments are omitted. These JSONs can also
be submitted to `POST /result/<source_chunk>`;
the tool itself never contacts a server.

Boolean cells accept TRUE/FALSE, case-insensitively. Array cells accept JSON
arrays or one scalar item; blank/EMPTY arrays become `[]`. Numeric probabilities
must be integers aligned with the CVE IDs; they are never inferred from text.
Missing probabilities are allowed only when no CVEs are present. String EMPTY
markers become empty strings. Missing rationale is an error unless the explicit
`--rationale-from-summary` option copies the existing summary. This option does
not generate new assessment evidence. All other required columns must be present.
The known `extracted_Filename` and `ai_cve_id_pattern` columns are ignored and
reported; unknown columns are errors. UTF-8 BOM and quoted CSV cells are supported.
Review columns selected by the packaged schema are required and validated, not
ignored. For nullable arrays, blank, EMPTY and the exact JSON literal null become
JSON null; explicit [] remains an empty array. Agreement requires null arrays;
disagreement requires nonempty, unique, schema-formatted arrays. JSON arrays and
single-item scalar shorthand are accepted; no agreement or review text is inferred.
With a legacy schema, non-contract rv_* columns remain ignored and reported, and
blank/EMPTY non-nullable arrays remain [].

The output directory must not already exist. All rows and result documents are
validated before creating it; write failures may leave a partial new directory.
Duplicate and progress behavior is shared with import, with CSV line locations
in conflict warnings. Progress goes to stderr; stdout contains one JSON summary.

## Import grouping and progress

`ai-import --results-bundle PATH` accepts an existing server-export ZIP, a
server-compatible chunk-result JSON, or a directory recursively containing
result JSONs. For JSON inputs, filenames and folders do not determine identity.
The current source package and generated schemas remain authoritative.

For arbitrary grouping, use a collection object with exactly `schema_version`
(`"1.0"`), `run_id`, `input_schema_checksum`, `output_schema_checksum`, and
`results`. Copy identities from the original source package. `results` maps
full commit SHAs to the same per-commit assessment objects as the output schema.
One collection may span source chunks; it must not claim a single `source_chunk`
or `input_checksum`. One large collection and many one-commit collections are
imported identically. Existing chunk envelopes are also accepted and validated.

Files are processed in sorted absolute-path order. Identical duplicate SHAs
are counted and skipped. Conflicting duplicates keep the first valid assessment
and reject the later assessment as a whole, warning with SHA, both locations,
and retained/rejected values for every differing field. Fields are never merged.
Duplicate keys within a JSON object are errors. Invalid assessments, unknown
SHAs and identity mismatches remain fatal; all input is validated before the
sidecar or reports change. Import replaces the current sidecar with the accepted
collection; it does not append assessments from previous import runs.

Progress and warnings go to stderr, with elapsed time and periodic discovery,
source-validation, file/commit-processing and final-summary messages. Normal
progress is throttled to about once per second; phase boundaries, first/last
files and conflicting-duplicate warnings are always shown. Stage 08 preparation
is not rerun during import.

## Server version provenance

`GET /api/version` returns the generating tool's `tool_version`, read directly
from its current `MANIFEST.json` during zipapp generation and embedded with
`version_source: MANIFEST.json` and `captured_at: zipapp_generation` metadata.
It is not inferred from the input bundle's `pipeline_version` or a stale imported
constant. Existing zipapps retain their snapshot; rebuild to use a newer version.

## Test entry points

`./run_tests` includes pagination and smoke-tool regression tests. Run
`./run_tests_ai output/serve_ai.pyz` to exercise the actual generated zipapp with
curl in an isolated temporary directory. The smoke tool checks live `/api`, batch
and chunk discovery, pagination against complete listings, and unpaginated API
and ZIP export. It handles empty/small listings and verifies returned results;
its uploads affect only the temporary copy, not the original server results.

## Selecting work for debug runs and retries

`/batches`, `/chunks`, and `/batch/<batch_id>` accept independent `limit` and
`offset` query parameters. An absent or zero `limit` means unlimited; an absent
`offset` means zero. Supplied values must be nonnegative integers and occur once.
Empty, malformed, negative, repeated and unknown parameters return HTTP 400 rather
than expanding the selected work. Offset skips items before limit caps the result;
order and full-collection totals are preserved. Beyond-end offsets return empty
lists. Batch detail returns `chunks: [{"chunk": "...", "result": "..."}]`,
without a separate `results` array. Pagination selects complete pairs; full-batch
metadata stays unchanged. A result URL does not imply a stored result exists.
`/batches` retains complete membership and `/chunks` remains a list of chunk URLs.
`/api` is never paginated.

Use `/batches?limit=2` for two complete batches, `/chunks?limit=5&offset=10` for
five selected chunks, or `/batch/batch_002` without parameters for a complete
batch retry. Clients must follow that selected listing and submit per-chunk
results; discovery does not execute analysis or remove previous results.
Rebuild Stage 08 and restart the regenerated zipapp to enable these options.

`GET /api` exposes a live JSON catalog generated by the executable HTTP route
registry in `serve_ai.pyz`, not by a separate document. It includes methods,
path parameters, descriptions from handler docstrings, content types, schema
links, effective upload limits and runtime authentication status (no secrets).
The same registry dispatches requests. Rebuild Stage 08 to update an existing
zipapp; the front page explains how clients use `/api` without duplicating it.

API entries are sorted by discovery/guide, contract assets, sources, validation,
and results/export, independent of decorator registration order. Per-route `group`
and `order` metadata remain in the executable registry. `path_parameters` describe
parameters and provide examples; role enums and concrete URLs use selected assets
and manifest IDs. Query examples follow the declared query contract. Each example
contains exactly `method` and `url`; no curl, body-file, schema or note fields.
The separate `request_body` contract declares whether a body is required, its
content type and schema. Single-role validation references `/schema/<role>` (use
the URL role); workflow validation describes an object requiring exactly the four
complete documents, with per-property schema links and no additional properties.
The URL selects trusted source context; submitted documents arrive in the POST
body, not as filenames or source chunk names. Route-specific descriptions take
precedence over shared handler docstrings, keeping these two operations distinct.
Empty source/batch listings produce no invented example IDs. Examples do not run
requests or upload anything; add authentication credentials separately when needed.

`/schema/result` is the sole final-result schema URL; the former output alias is
removed. Root package artifact names and the `output_schema_checksum` envelope
field are unchanged. `/metadata/<name>` supplies trusted per-chunk envelope fields;
bare `/metadata` is not an endpoint. Copy identities/checksums from it, then add
assessment fields, counts and status rather than calculating hashes with an LLM.

AI assessment is advisory. The ordinary pipeline runs stages 00–07 and does not
require an AI service. Stage 08 prepares an independent work package from the
stage 04 prefilter-kept commits, before scoring and postfiltering. It does not
change scores, priorities, or cherry-pick test results.

## Enabling AI

The configuration alone decides (v20.1.0; there is no `--ai` option). The AI
workflow is active when the config declares an `ai` section, unless
`ai.enabled` is `false`. When active:

- a full `run` includes Stage 08 after Stage 07;
- `validate` and Stage 00 check `ai.prompts_dir`, `ai.schemas_dir` and
  `ai.front_page_path`, including required assets and contract consistency. Defaults
  are `ai/prompts`, `ai/schemas` and `ai/ai_server_front_page.md` under the initial
  configuration directory.

With no `ai` section or `"enabled": false`, product AI resources are not
validated and Stage 08 does not run; `run --stage 8` / `--from 8` are refused.
Tool-bundled schema correctness checks still run independently of this flag.

## Prepare

A full run prepares the package. To rerun only Stage 08:

```sh
python3 kcommit_pipeline.py run --config product.json --stage 8
```

`ai.chunk_size` counts commits per chunk (default 100); `ai.batch_size` counts
chunks per batch (default 10). Both require positive integers, not booleans.
`ai.prompts_dir` selects role prompts. Inputs use `ai_analysis_input/batch_001/001.json`,
etc., with global chunk numbering and at least three digits. The last batch may
be smaller. Empty input produces one empty chunk in one batch.

The manifest records sizes, total chunks/batches, and an ordered `batches` list
with `batch_id`, `batch_number`, `chunks` and `total_commits`. Checksums use full
relative chunk paths. Chunk metadata includes `batch_number`, `total_batches`
and `chunk_in_batch`. Batch size contributes to the run identity.
Use `/batches` and `/batch/<id>` to discover work; `/chunks` still lists all inputs.
Submit one result per chunk to `/result/<source_chunk>`. Result storage and ZIP
export/import preserve subfolders. Regenerate packages after configuration migration.
Rerun Stage 08 with `--force` to replace old flat outputs. Update custom prompts
and front pages to describe batch paths; do not manually move existing chunks.
The sample result schema is `configs/ai/schemas/result.json`.
Stage 08 writes numbered JSON chunks, input and output schemas, a prompt, a
checksummed bundle manifest, and `serve_ai.pyz` to the configured output
directory. An empty prefilter set produces an empty chunk. Keep these files
together until importing the returned results.

## Server front page

Set `ai.front_page_path` in `configs/conf.d/07_ai.json` to an external UTF-8
Markdown file. The shipped value is `${TOOLDIR}/configs/ai/ai_server_front_page.md`.
Stage 08 validates the file, copies it to `output/ai_server_front_page.md`,
and embeds it in `serve_ai.pyz`; missing, empty, or invalid UTF-8 files fail
preparation before outputs are modified. The portable bundle needs no access
to the original config directory. Regenerate it after editing the Markdown.

`GET /` serves raw Markdown with
`Content-Type: text/markdown; charset=utf-8`. It uses the same authentication
and access logging as other endpoints. Rendering HTML is not required; this
keeps the zipapp dependency-free. The guide explains the purpose, workflow,
endpoints, result requirements, and network safety without replacing selected prompts.
The guide is presentation-only and does not change analysis run identities.

## Analyze remotely

Copy `serve_ai.pyz` to the analysis machine and start it with Python 3:

```sh
python3 serve_ai.pyz -l ./ai-server.log --auth 'user:password'
```

By default, the server detaches into the background and listens on loopback
(`127.0.0.1:8000`). Daemon mode requires explicit `-l PATH` or `--log-file PATH`.
It prints its PID, actual listening address, and log
location. Stop it with `kill PID` using that printed PID. SIGTERM and SIGINT
close the server cleanly. Positional `port host` arguments remain supported;
port 0 selects an available port. The old default was `127.0.0.1:8001` in the
foreground. Regenerate existing bundles with Stage 08 to receive the new code.

`-d`, `--debug`, and `--no-daemon` are aliases for one foreground option;
`--debug` does not add verbose logging. Background mode requires Unix.
For foreground operation without a log file, run `./serve_ai.pyz -d`; all logs
go to stderr. To select file-only logging instead:

```sh
python3 serve_ai.pyz -d --log-file "$HOME/kcommit-analyze-ai-server.log" \
  --auth 'user:password' 8000 127.0.0.1
curl --user 'user:password' http://localhost:8000/chunks
```

There is no default log-file path. `-l PATH` and `--log-file PATH` are aliases:
when supplied, logs append only to that file, regardless of foreground or daemon
mode. An unwritable file causes startup failure with no fallback to stderr.
Without this option, foreground mode logs only to stderr; daemon mode rejects
the invocation before detaching. New log files use mode 0600. Startup diagnostics
may still appear on stderr when startup fails. Startup and shutdown lines are
marked `SERVER`. Foreground startup also prints one flushed summary to stdout,
independent of log selection, showing debug mode, PID, bind address, log location
(or stderr), and the connection URL. The daemon's startup summary includes its URL.
The actual bound port is used; for `0.0.0.0`, the URL uses local `127.0.0.1` while
retaining the wildcard bind address. No credentials appear in these summaries.
Each request emits one completion line with UTC time, client, escaped method/path,
status, duration in milliseconds, and a safe reason. Authentication failures,
invalid uploads, unknown paths, unsupported methods, and internal errors are
logged without duplicate default messages. Timeouts and disconnects are logged
once; status is `-` if no response was started, otherwise the attempted status.
Idle connections closed without a request do not produce access lines. Query
strings, request bodies, credentials, and exception text are omitted. HTTP only;
no TLS or proxy handling is added:

```text
2026-10-09T00:10:03Z client=127.0.0.1 method="GET" path="/chunks" status=200 duration_ms=2 reason=ok
2026-10-09T00:10:05Z client=127.0.0.1 method="POST" path="/result/batch_001/001.json" status=400 duration_ms=1 reason=invalid_result
```

`--auth USER:PASSWORD` protects all endpoints using HTTP Basic authentication.
Both parts must be nonempty; passwords may contain colons. Missing, malformed,
or incorrect credentials receive a 401 challenge before endpoint processing.
Clients that support URL credentials may use `http://user:password@host:8000/`;
prefer an explicit client authentication option, and use the browser's login
prompt rather than relying on credential-bearing URLs. Special URL characters
require percent-encoding. Command-line credentials can appear in shell history
and process listings. Basic authentication is not encryption: plain HTTP exposes
credentials and data to interception. Use only on a trusted network or behind
TLS termination. Omitting `--auth` leaves all endpoints unauthenticated and
produces a startup warning. This is minimal shared-password access control,
not a production-hardened public web service. Connections have a 10-second
socket timeout; the server processes requests serially.

Use `GET /contract`, its listed `/prompt/<name>` assets, `GET /schema/input`, `GET /schema/result`,
`GET /chunks`, and `GET /chunk/<name>` to inspect the work. Return one schema-
conforming result document per chunk using `POST /result/<name>`.
POST enforces authentication, size limits, validation and atomic replacement,
returning HTTP 200 with `{"status":"ok"}`. PUT returns HTTP 405; use `/` for the guide.
Regenerate and restart the zipapp after changing server code or assets. Results may
be partial; a complete result must cover every source SHA. `GET /result/<name>`
retrieves an uploaded result. `GET /export` returns a ZIP containing the source
manifest, chunks, and any accepted results. Keep the ZIP for the import step.

Do not assume mitigation settings or infer CVE IDs that are not supported by
source commits. Risk value `none` must be used alone; CVE probabilities align
positionally with CVE IDs. Human review is required before backporting.

## Import

Transfer the exported ZIP back to the pipeline machine and run:

```sh
python3 kcommit_pipeline.py ai-import --config product.json --results-bundle results.zip
```

The importer checks manifest and schema identities, exact chunk bytes, source
SHA membership, and result fields before writing a result sidecar. The report
path then decorates report-only commit copies with `ai_analysis` when the
sidecar `run_id` matches the current bundle. The relevant and filtered JSON
reports and commit-detail shards can carry this advisory object; the HTML
commit detail pane shows an advisory card. Existing scoring caches and ranking
remain unchanged. A later Stage 08 run with a different identity makes the
old result sidecar inapplicable. A missing result for a commit means no AI
assessment was returned; it must not be interpreted as a negative finding.

## QA before committing

Run `./run_tests` from the repository root and review any changes to the
HTML report, JSON exports, and imported sidecar. If tests cannot be executed,
do not commit. The `--stage 8 --force` path can remove Stage 08 outputs; keep
a copy of the exported result ZIP until import has been verified.
