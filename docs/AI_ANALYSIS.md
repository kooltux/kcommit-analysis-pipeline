# Optional AI analysis workflow

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
be submitted to `PUT /result/<source_chunk>` or `POST /result/<source_chunk>`;
the tool itself never contacts a server.

Boolean cells accept TRUE/FALSE, case-insensitively. Array cells accept JSON
arrays or one scalar item; blank/EMPTY arrays become `[]`. Numeric probabilities
must be integers aligned with the CVE IDs; they are never inferred from text.
Missing probabilities are allowed only when no CVEs are present. String EMPTY
markers become empty strings. Missing rationale is an error unless the explicit
`--rationale-from-summary` option copies the existing summary. This option does
not generate new assessment evidence. All other required columns must be present.
The known `extracted_Filename`, `ai_cve_id_pattern` and `rv_*` columns are ignored
and reported; unknown columns are errors. UTF-8 BOM and quoted CSV cells are supported.

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
`offset` query parameters. Missing, empty, non-integer or nonpositive `limit`
means unlimited; missing, empty, non-integer or negative `offset` means zero.
The first repeated value wins. Offset skips items before limit caps the result;
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

AI assessment is advisory. The ordinary pipeline runs stages 00–07 and does not
require an AI service. Stage 08 prepares an independent work package from the
stage 04 prefilter-kept commits, before scoring and postfiltering. It does not
change scores, priorities, or cherry-pick test results.

## Enabling AI

The configuration alone decides (v20.1.0; there is no `--ai` option). The AI
workflow is active when the config declares an `ai` section, unless
`ai.enabled` is `false`. When active:

- a full `run` includes Stage 08 after Stage 07;
- `validate` and Stage 00 check that `ai.prompt_path`, `ai.front_page_path` and
  `ai.result_schema_path` exist and have valid content (non-empty UTF-8
  Markdown; a JSON object schema with `properties.results`). When unset they
  default to `ai/ai_analysis_prompt.md`, `ai/ai_server_front_page.md` and
  `ai/ai_analysis_result_schema.json` under the initial configuration directory.

With no `ai` section or `"enabled": false`, nothing AI-related runs or is
validated, and `run --stage 8` / `--from 8` are refused.

## Prepare

A full run prepares the package. To rerun only Stage 08:

```sh
python3 kcommit_pipeline.py run --config product.json --stage 8
```

`ai.chunk_size` counts commits per chunk (default 100); `ai.batch_size` counts
chunks per batch (default 10). Both require positive integers, not booleans.
`ai.prompt_path` selects the prompt. Inputs use `ai_analysis_input/batch_001/001.json`,
etc., with global chunk numbering and at least three digits. The last batch may
be smaller. Empty input produces one empty chunk in one batch.

The manifest records sizes, total chunks/batches, and an ordered `batches` list
with `batch_id`, `batch_number`, `chunks` and `total_commits`. Checksums use full
relative chunk paths. Chunk metadata includes `batch_number`, `total_batches`
and `chunk_in_batch`. Batch size contributes to the run identity.
Use `/batches` and `/batch/<id>` to discover work; `/chunks` still lists all inputs.
Submit one result per chunk to `/result/<source_chunk>`. Result storage and ZIP
export/import preserve subfolders. Legacy flat bundles remain readable.
Rerun Stage 08 with `--force` to replace old flat outputs. Update custom prompts
and front pages to describe batch paths; do not manually move existing chunks.
The sample result schema is `configs/ai/ai_analysis_result_schema.json`.
Stage 08 writes numbered JSON chunks, input and output schemas, a prompt, a
checksummed bundle manifest, and `serve_ai.pyz` to the configured output
directory. An empty prefilter set produces an empty chunk. Keep these files
together until importing the returned results.

## Server front page

Set `ai.front_page_path` in `configs/conf.d/07_ai.json` to an external UTF-8
Markdown file. The shipped value is `${CONFIGDIR}/ai/ai_server_front_page.md`.
Stage 08 validates the file, copies it to `output/ai_server_front_page.md`,
and embeds it in `serve_ai.pyz`; missing, empty, or invalid UTF-8 files fail
preparation before outputs are modified. The portable bundle needs no access
to the original config directory. Regenerate it after editing the Markdown.

`GET /` and `GET /README.md` serve identical raw Markdown with
`Content-Type: text/markdown; charset=utf-8`. They use the same authentication
and access logging as other endpoints. Rendering HTML is not required; this
keeps the zipapp dependency-free. The guide explains the purpose, workflow,
endpoints, result requirements, and network safety without replacing `/prompt`.
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
2026-10-09T00:10:05Z client=127.0.0.1 method="PUT" path="/result/1.json" status=400 duration_ms=1 reason=invalid_result
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

Use `GET /prompt`, `GET /schema/input`, `GET /schema/output`,
`GET /chunks`, and `GET /chunk/<name>` to inspect the work. Return one schema-
conforming result document per chunk using `PUT /result/<name>` or
`POST /result/<name>`. Both share authentication, size limits, validation and
atomic replacement, returning HTTP 200 with `{"status":"ok"}`. Rebuild Stage 08
and restart the generated zipapp to enable POST. Results may
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
