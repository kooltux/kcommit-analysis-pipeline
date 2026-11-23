# Optional AI analysis workflow

## HTTP submission policy

The server ignores unknown contribution fields by default; `--strict-schema`
rejects them. Filtering covers the closed combined-role object, role envelopes,
and per-commit assessment property sets resolved from the selected role schemas.
It never removes result SHA keys, invents missing fields, coerces defined values,
or changes identities or coverage. All canonical checks run after filtering.
Role validation, workflow validation and submission share this policy in both APIs;
separate validation calls remain optional. Served output schemas stay exact.
The catalog reports the active `schema_policy`. Normal logs contain escaped
ignored paths, not values; explicit `--save-posts` still captures raw bodies.
Stored-record verification and offline imports are always strict.

## Versioned runtime interfaces

Version v21.7.0 exposes two self-contained APIs: `/v1/api` for packaged delivery
and `/v2/api` for bounded planned delivery. `/` is the readable entry guide for
humans and AI clients. These are the only catalog endpoints. All unversioned API
paths, bare `/v1` and bare `/v2` return 404 without aliases or redirects.
Rebuild the pipeline and its packages from scratch. No HTTP migration is provided.

Both prefixes expose `/api`, `/version`, `/contract`, `/prompt/<name>`,
`/schema/<name>`, optional `POST /validate/role/<role>`, and `GET /export`.
V1 uses `GET /v1/chunks`, `GET /v1/chunk/<name>`, optional
`POST /v1/validate/workflow`, `POST /v1/result` and `GET /v1/result/<sha>`.
V2 uses `GET /v2/plan`, `GET /v2/group/<group_id>`, optional
`POST /v2/validate/<group_id>`, `POST /v2/result/<group_id>` and
`GET /v2/result/commit/<sha>`, without aliases for superseded v2 paths.
GET planning accepts positive `max_commits_per_group`, `max_bytes_per_group`
and optional `max_groups`. Commits are implicit; the group cap returns a stable
prefix. Group retrieval does not depend on the plan cache.
See [AI workflow agent handoff](AI_WORKFLOW_AGENTS.md) for the independent prompts
and required matching catalog/context documents.
Catalogs derive from executable routing, contain only their own namespace and
include all shared-document access, request bodies, responses, authentication,
size limits, parameter choices and examples. IDs not yet created are never invented.

Each `/contract` indexes the effective served schemas and complete role prompts.
URLs stay within the selected API. Checksums and byte counts identify exact served
bytes, including appended schemas, not the raw prompt file or archive envelope.
Prompt-embedded schemas match the corresponding effective HTTP schemas. Workflow
schema references stay in their own version; catalog fragments resolve locally.
Original archived schemas remain provenance rather than HTTP request definitions.

## Analysis identity and canonical records

`lib/ai_canonical.py` hashes source commits, product evidence and contract assets
into a grouping-independent analysis identity. Stage 08 records `analysis_id`;
both APIs expose that identity as `run_id`. Physical archive identities are distinct.
Changing a chunk selection, delivery plan or group never changes record identity.

Both source forms return exactly `run_id`, `commits`. Role documents require
exactly `run_id`, `role`, `results`, keyed by full source commit SHA. Delivery names,
plan/group IDs, checksums, counts and status are not contribution-envelope fields.
The three submitted roles must cover the same selected SHA set; v2 additionally
requires the complete identified group. Other commits stay unassessed; missing
findings are not negative classifications.

The shared gate validates source membership, identities, roles, fields, limits and
coverage before assembling values. Submit exactly `analyst`, `cve`, `reviewer`;
there is no fourth client-produced final document. Role validation checks only that
role. Workflow validation and submission share the deterministic assembly gate.
Validation is write-free, including against existing accepted findings.

The server preserves specialist values and advisory Reviewer proposals in records
containing `run_id`, `commit`, `assessment`, stored at `<aa>/<bb>/<full-sha>.json`.
Successful submission returns `status: stored`, `run_id`, and `results` mapping each
submitted SHA to the SHA-256 of its exact record bytes. Retrieve records from either
API to verify. Reassessment replaces supplied SHAs only. GET/export never rewrite,
create or migrate result files. Canonical records persist across server restarts;
invalid current-run records fail rather than being silently exported.

Publication prevalidates the submitted set and is atomic per SHA, not across a
whole batch. One writer per root is supported. Interprocess locks, whole-batch
rollback, and transactional report publication are not provided.

## Delivery configuration

`ai.chunk_size` counts commits per packaged chunk (default 100); `ai.batch_size`
counts chunks per archive folder (default 10). Both require positive integers, not
booleans. Inputs are archived as `ai_analysis_input/batch_001/001.json` etc. Empty
input retains one empty packaged selection. Archive paths are not result identities.

`/v1/chunks` supports nonnegative integer `limit` and `offset`, applied in stable
order. Absent/zero limit means unlimited. Invalid, repeated, negative, empty or
unknown parameters return 400; rejected pagination never expands selected work.
Catalogs are never paginated. V2 implicitly partitions all packaged source commits.

`ai.planning` accepts positive `max_commits` (default 100), `max_bytes` (1048576),
and `cache_entries` (32); unknown options are rejected. Use
`configs/ai_planning.example.json` to override defaults. Stage 08 verifies default
plan feasibility before publishing assets. V2 deterministically partitions all
packaged SHAs and counts exact source-document bytes. GET query parameters
`max_commits_per_group` and `max_bytes_per_group` override the first two defaults;
`cache_entries` remains internal. Optional `max_groups` returns a stable prefix.
Group definitions persist independently of the bounded plan cache and survive
restart. Only unknown groups return 404; eviction does not invalidate group IDs.
An oversized single commit is rejected, not truncated or omitted. Byte limits
are not model token/context feasibility.

## Directory-only integration

Stage 08 snapshots `ai.prompts_dir`, `ai.schemas_dir`, and `ai.front_page_path`.
Defaults resolve beneath the initial configuration directory to `ai/prompts`,
`ai/schemas`, and `ai/ai_server_front_page.md`; there is no implicit fallback to
installed samples. Select tool resources explicitly through TOOLDIR if required.
Removed settings `prompt_path` and `result_schema_path` are not supported.

Selected prompts/schemas affect identity; pipeline scores and delivery grouping do
not. The portable server contains source/product/contract snapshots, a readable
guide, and pinned tool-version metadata. Generation validates dependencies and
constructs the archive before replacing live assets. Package publication is per-file/
per-tree, not a filesystem-wide transaction. Do not transplant old server stores.

## Prepare and serve

AI runs when an `ai` section is declared unless `ai.enabled` is false. A full run
includes Stage 08 after Stage 07. Configuration validation and Stage 00 check required
resources. Explicitly requesting disabled Stage 08 is refused.

```sh
python3 kcommit_pipeline.py run --config product.json
# Prepare Stage 08 only from coherent source/product caches:
python3 kcommit_pipeline.py run --config product.json --stage 8
./output/serve_ai.pyz -d --auth 'user:password'
```

Defaults are 127.0.0.1:8000. `-d`, `--debug`, `--no-daemon` select foreground mode.
Background mode requires `-l PATH` or `--log-file PATH`. Foreground logs go only to
stderr unless a file is selected; explicit file logging never silently falls back.
Startup prints the bind address, connection URL and log destination. Background
readiness is reported only after binding succeeds.

`/v1/version` and `/v2/version` return the version captured from MANIFEST.json at
package generation, separate from the source bundle's `pipeline_version`. They do
not consult the repository at runtime. `/` serves the snapshotted human/AI guide.
Normal authentication applies to the entry guide and both APIs. Removed unversioned
paths return 404 even with authentication enabled. Plain HTTP does not encrypt
credentials/evidence: use trusted networking or HTTPS termination. Unauthenticated
operation is unrestricted and emits a warning.

## Prompts, validation and diagnostics

Analyst owns non-CVE fields; CVE expert owns supported source-message CVE candidates
and probabilities; Reviewer owns advisory `rv_*` proposals. Only CVE expert may use
configured research tools. The external orchestrator performs HTTP requests,
validation, retries and handoffs; LLMs return documents, not server operations.
Use each API's complete role prompts and effective schemas, appending trusted
sources and prior validated outputs separately. Reconcile specialist SHA selections
before review/submission. Do not submit a failure report as an assessment.

POST raw JSON with one Content-Length, one application/json Content-Type and no
Transfer-Encoding. Bodies must be 1 byte to 10 MiB. Duplicate keys, NaN, fenced JSON,
unknown SHAs and invalid fields are rejected. Structured 400 diagnostics may identify
role, SHA, field, limit and actual size without echoing rejected assessment text.
Validation never corrects values. Successful JSON/Markdown may negotiate text/plain
without changing bytes; errors stay JSON and ZIP stays binary.

`-s` / `--save-posts` saves each recognized POST's latest body and Markdown exchange
report under `<zipapp>.debug/`, e.g. `v1/ok/validate/workflow` or `v2/error/result`.
Reports show request/response context and redact authentication/cookie headers.
Treat them as sensitive: debug roots are 0700 and files 0600. Save failures are
logged without changing responses. Unknown or authentication-rejected requests are
not saved. Completion logs record status, safe reason and duration once per request;
query secrets are not included.

## Import and reporting

Both APIs export a deterministic ZIP of original manifest/source/contract provenance
and accepted canonical findings. Import on the pipeline host:

```sh
python3 kcommit_pipeline.py ai-import --config output/pipeline_config.json \
  --results-bundle results.zip
```

Import validates provenance, run identity, source membership and assessment fields
before changing findings or reports; it never reruns Stage 08. Grouping does not
change accepted values or membership. Stage 07 attaches findings to deep copies
before one standard report-generation pass.

## Single-pass AI report scope

AI findings are validated before any standard report writes. Stage 07 then attaches
independent copies once, after the relevant top-N selection, and decorates the
existing prefilter/postfilter-dropped collections without promoting extra commits.
The standard report stage emits every format from those same annotated collections;
there is no second report/HTML/archive generation pass or Stage 08 regeneration.
JSON/detail and HTML table indexes retain the full baseline assessment, including
Reviewer proposals without applying them. Missing current findings have no
`ai_analysis` field; stale cached annotations are removed during attachment.
`ai_analyzed_commits` counts accepted findings; `ai_reported_commits` counts unique
assessed SHAs within the displayed relevant/filtered scope. Scoring/profile/rule
values, ordering, cache bytes and source-package assets remain unchanged.
CSV and standalone/combined XLSX/ODS commit tables share eight advisory columns:
AI assessed, security fix, bug fix, product impact, backport effort, recommendation,
summary and Reviewer agreement. Columns are appended after the existing base/filter
columns only when that table contains an assessment; unassessed rows have blank AI
cells, not negative findings. Boolean findings display Yes/No. Formula-like AI text
is prefixed with an apostrophe in tabular output; stored findings and JSON stay exact.
Full CVE details and Reviewer correction proposals remain in JSON/detail and HTML
outputs; proposals never replace baseline recommendations. Profile/rule/matrix score
tables do not acquire AI columns. Tables without AI retain original headers/rows.
Earlier report/acceptance batches had user-reported QA passes. Those historical
results do not validate this two-API redesign.


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
store, sidecar or reports change. Imports accumulate for the current run; a valid
assessment in a later import replaces the existing assessment for that SHA.
The first-wins rule above applies only to duplicates within one incoming batch.
Publication is atomic per SHA, not across the whole import. The compatibility
sidecar is refreshed after successful canonical-record publication.

Progress and warnings go to stderr, with elapsed time and periodic discovery,
source-validation, file/commit-processing and final-summary messages. Normal
progress is throttled to about once per second; phase boundaries, first/last
files and conflicting-duplicate warnings are always shown. Stage 08 preparation
is not rerun during import.


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
Output uses the original `batch_NNN/NNN.json` paths and offline import result
envelopes, including original identities, exact-byte checksums and complete or
partial status. Chunks without assessments are omitted. Import these JSONs using
`ai-import --results-bundle`; they are not contribution-only HTTP request bodies.
The tool itself never contacts a server.

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

The output directory must not already exist. All rows and result documents are
validated before creating it; write failures may leave a partial new directory.
Duplicate and progress behavior is shared with import, with CSV line locations
in conflict warnings. Progress goes to stderr; stdout contains one JSON summary.


## Acceptance coverage and execution status

For the current v21.6.0 interface, the user confirmed QA passing after schema-policy
completion on 2026-11-19. No exact count or fresh log was supplied for that final
run; see [current QA notes](AI_V2_QA.md). Release-metadata changes require a new
full run before committing. The older validation history below is retained.

The previous nine-item plan was closed on user-reported QA; that historical pass
is distinct from validation of the v21.5.0 redesign.

On 2026-11-18 the user manually applied the patch and reported `./run_tests`
passing 100%. Exact counts and logs were not supplied. This is user-reported
QA, not an independently executed run against the Denux working tree.

The earlier sandbox run completed with 1,907 passed and 7 failed.
The same seven tests failed against the original snapshot; kconfiglib was
absent in that sandbox. These results are separate from the user's local pass.

Browser interaction, model context feasibility, whole-batch transactions and
multiple writers remain outside the claimed coverage.

| Boundary | Regression coverage |
| --- | --- |
| Isolated catalogs, rejection of old routes, live registry | `test_ai_server_api.py` |
| Exact documents, local links, schema/prompt agreement | `test_ai_api_documents.py`, `test_ai_prompt_body.py` |
| Response contracts and protocol errors | `test_ai_api_responses.py` |
| Packaged selection and safe pagination | `test_ai_batch_entries.py`, `test_ai_server_pagination.py` |
| Durable v2 groups and API/group equivalence | `test_ai_versioned_runtime.py`, `test_ai_acceptance_closure.py`, `test_ai_group_http.py` |
| Default/strict schema policy and publication safety | `test_ai_schema_policy.py` |
| Assembly, advisory values, receipt timing, rejection safety | `test_ai_assembly.py`, `test_ai_upload_policy.py`, `test_ai_server_upload_methods.py` |
| Read-only access and canonical persistence | `test_ai_runtime_persistence.py` |
| CLI/authentication/logging/framing/diagnostic saves | `test_ai_server_runtime.py`, `test_ai_save_posts.py`, `test_ai_structured_errors.py` |
| Live export/import through actual report writers | `test_ai_end_to_end.py` |
| Portable code assets and module initialization | `test_ai_code_assets.py`, `test_ai_embedded_runtime.py`, `test_ai_runtime_modules.py` |
| Standalone two-API smoke tool | `test_ai_smoke_discovery.py` |

Obsolete tests for global catalogs, chunk-bound HTTP uploads, batch-navigation APIs
and live legacy migration are replaced by current-interface tests, not skipped or
hidden from collection. Pure archive/source validation and host import/store tests
remain independent of the public HTTP surface.

## Test entry points

```sh
KCAP_TEST_LOG=./qa-full-v21.7.0.log ./runtests
./run_tests_ai output/serve_ai.pyz
```

The smoke tool copies the package to a temporary directory, starts a loopback server,
checks both APIs/shared documents/source delivery/gates/export, then stops the child.
It never changes the operator's original result store.
