# Kernel commit analysis API

## 1. For human readers

This server shares kernel commit analysis inputs and accepts validated results.
It serves instructions, JSON schemas, and source chunks, stores assessments,
and provides an export ZIP. It does not perform the analysis itself.

This reference is for human reviewers, AI clients, and CI jobs. Assessment
instructions live in `/prompt/<name>` assets listed by `/contract`; schemas define exact data contracts.

### Batch navigation

`GET /batches` lists batches and `/batch/<batch_id>` lists their chunk/result
URLs. `/chunks` remains the complete listing. `ai.batch_size` counts chunks per
folder (default 10); `ai.chunk_size` counts commits per chunk (default 100).
Preserve paths such as `batch_002/011.json` in `source_chunk` and result URLs.
Process every chunk in an assigned batch, submitting a separate result per chunk.

Optional `limit` and `offset` apply only to `/batches`, `/chunks`, and
`/batch/<batch_id>`. An absent or zero `limit` means unlimited; an absent `offset`
means zero. Supplied values must be nonnegative integers and occur exactly once.
Empty, malformed, negative, repeated or unknown query parameters return HTTP 400;
they never silently expand the work selection. Offset is applied first in existing
order; out-of-range offsets return empty lists. No source work is changed.
`/batches?limit=2` selects two complete batches; `/chunks?limit=5&offset=10`
selects five chunks after skipping ten. `/batch/batch_002?limit=3` selects three
chunks in that batch; omit both parameters to retry the complete batch.
Each `/batch/<batch_id>` entry in `chunks` is a `{"chunk": "...", "result": "..."}`
object; there is no separate `results` array. Pagination keeps each pair together.
Result URLs exist in discovery even before upload. Totals remain full-collection values, and
`/api` always returns the complete catalog, even with pagination parameters.

### Access and scope

GET requests are read-only. POST to `/result/<name>` replaces the stored result;
POST to validation gates checks documents without storing them.
When authentication is enabled, use the operator-provided credentials; browsers
can use the HTTP login prompt. Assessments remain advisory. This server is an
exchange interface, not an autonomous reviewer or a backport approval system.

### Live API discovery

Human readers, AI clients and CI jobs should retrieve `GET /api` for the live
JSON API catalog. It is generated from the same executable route registry that
dispatches requests, using handler docstrings and effective route contracts.
It describes methods, paths, parameters, content types, schema links and upload
limits. Authentication status comes from the running server; no credentials
are exposed. `/api` requires authentication whenever the server enables it.
Each route's `responses` maps HTTP status strings to descriptions, content types,
schemas and illustrative examples when provided. Resolve catalog-local `$ref`
values against this `/api` document: `#/response_schemas/...` defines shared body
schemas and `#/error_responses/...` defines shared error responses. Existing
`/schema/...` references still identify assessment/input schemas, not acknowledgements.
`protocol_responses` lists shared routing/protocol errors. Authentication errors
appear on routes only when enabled; errors always use application/json, including
for Markdown/ZIP endpoints. ZIP success bodies are marked binary, not JSON.
Validation returns status valid without storing anything; upload returns status ok.
Examples are illustrative, not real validation tickets or trusted source metadata.
This guide explains usage; it does not maintain a second endpoint catalog.

The catalog orders routes by discovery/guide, contract assets, source work,
validation, then results/export. Each entry has a group and order, path-parameter
descriptions/examples, and concrete request examples using this package's IDs.
Role values come from the selected assets or the validation route's role contract.
Example objects contain only `method` and `url`, including concrete path/query
parameters. They contain no curl commands, body filenames, schemas or extra notes.
Read the separate `request_body` contract for POST payload requirements; the
method/URL example alone is not a complete request. Role validation requires the
complete role JSON document in the body, conforming to `/schema/<role>` with the
URL role substituted. Workflow validation requires an object with exactly four
complete documents: `analyst`, `cve`, `reviewer` and `result`; each has its own schema
link. Neither validation endpoint runs an AI model or looks up saved role outputs.
GET result examples may return 404 until an assessment has been uploaded.

### Trusted metadata

Use `/metadata/<name>` for the source chunk selected from `/chunks` or `/contract`.
There is no bare `/metadata` endpoint. Copy its `schema_version`, `run_id`,
`source_chunk`, `input_checksum`, `input_schema_checksum`, `output_schema_checksum`
and `total_commits` into role/result documents. Add your `results`,
`analyzed_commits`, `analysis_status` and intermediate `role` as appropriate.
The input checksum hashes exact archived bytes; never ask an LLM to calculate it.
`/schema/result` is the final contract; the redundant output-schema URL is removed.
For every intermediate role and final result, output_schema_checksum refers to
the final result.json schema, never the role-specific schema.

`GET /api/version` reports `tool_version`, captured from the generating tool's
`MANIFEST.json`, with `version_source` and `captured_at` provenance. The version
is embedded in the zipapp, remains unchanged when the repository changes, and
does not require repository access at runtime. It is separate from the input
bundle's `pipeline_version`; normal authentication applies and it is not paginated.

## 2. For AI clients

### Context and task

You are the analysis client, not the server. Your task is to assess the supplied
kernel commits under the selected `/prompt/<name>` instructions, using available
evidence. Analyst returns `/schema/analyst`, CVE expert returns `/schema/cve`,
and Reviewer returns `/schema/reviewer`; only Assembler returns `/schema/result`.
This API guide explains access and submission; it does not replace those
assessment instructions.
Do not infer that a missing result is a negative assessment.

### Role workflow

The client orchestrates this workflow for each selected chunk. The server serves
assets and validates documents; it does not run AI models or invoke the roles.
The operator or external orchestrator performs every server API
request described below and supplies schemas, chunks, trusted metadata and prior
role outputs as attachments or quoted content. LLMs return documents only;
the orchestrator validates, retries, routes handoffs and stores accepted results.
Only the CVE expert may use configured `web_search` to verify source-message CVE
candidates, without adding IDs absent from the source commit message. Analyst and
Reviewer use supplied evidence only; Assembler performs mechanical assembly only.
These capabilities do not depend on model or provider.

1. Analyst and CVE expert independently read the same original chunk and metadata.
   Analyst assesses non-CVE classifications, product impact, backport effort and
   recommendations under `/prompt/analyst` and `/schema/analyst`. Validate its
   complete intermediate document at `/validate/role/analyst/<name>`.
2. CVE expert owns supported CVE IDs and their probabilities under `/prompt/cve`
   and `/schema/cve`; it does not rewrite Analyst assessments. Validate its
   complete intermediate document at `/validate/role/cve/<name>`. Both specialist
   outputs must pass their gates before being passed to Reviewer.
3. Reviewer reads the original chunk and both validated specialist outputs. It
   checks evidence, identities, coverage and uncertainty under `/prompt/reviewer`
   and `/schema/reviewer`, recording agreement or proposed corrections in `rv_*`
   without rewriting specialist values. Validate the complete review document at
   `/validate/role/reviewer/<name>` before passing all three outputs to Assembler.
4. Assembler mechanically joins validated contributions by full commit SHA under
   `/prompt/assembler`, preserving values exactly. Do not apply review recommendations.
   Produce one `/schema/result` document per chunk. Mark missing contributions as
   partial; never fabricate assessments or merge different chunks.
5. POST an object containing exactly `analyst`, `cve`, `reviewer` and `result`
   documents to `/validate/workflow/<name>`. All gates require HTTP 200 and
   `status: valid` and store nothing. Only after workflow validation, POST the
   unchanged final result to `/result/<name>` and GET that URL to verify acceptance.

If required schemas or inputs are missing, unreadable or inconsistent, stop and
report the failure to the caller. Never POST a failure report as an assessment.

### Using this server

1. Retrieve `/api` and `/contract`, then the listed `/prompt/<name>` and `/schema/<name>` assets.
2. Retrieve the selected batch or chunk listing, preserving any `limit` and
   `offset`. Use its run ID and URLs exactly; do not guess filenames or replace
   a debug subset or single-batch retry with the unrestricted global listing.
3. Download a listed chunk and `/metadata/<name>`. Copy authoritative identity and
   checksum fields from that metadata, never from LLM calculations. Follow the role
   workflow above, including every validation gate, without expanding selected work.
4. Build a schema-conforming result. Use partial status if only a subset was
   assessed; do not fabricate results or unsupported CVE IDs.
5. When authorized, submit to `POST /result/<name>`.
   POST validates and atomically replaces the result for that source chunk.
6. Check for HTTP 200 and `{"status":"ok"}`, then GET the same result URL to
   verify acceptance. A rejected upload is not a completed submission.

### Result contract

- Follow `/schema/result` exactly, including field names and types.
- Preserve run ID, source chunk name, schema checksums, and source commit IDs.
  `input_checksum` is SHA-256 of the original downloaded chunk bytes, not
  reserialized JSON. `total_commits` must match the source chunk.
- `analyzed_commits` must equal the number of result entries. A complete result
  covers every source commit in the chunk; a partial result may cover a subset.

Do not invent missing assessments or unsupported CVE IDs. Assessments are
advisory, not proof of backport safety.

## 3. For automation and testing

CI jobs can discover, retrieve, and validate data without performing assessments.
Keep read-only checks separate from authorized uploads. Never upload placeholder
results as a connectivity test.

### HTTP requirements and responses

- POST bodies must be 1 byte to 10 MiB with one `Content-Length` and one
  `Content-Type: application/json` header, without `Transfer-Encoding`.
- Successful uploads return HTTP 200 and `{"status":"ok"}`.
- HTTP 400 rejects an invalid upload; read the error and correct the submission.
- HTTP 401 indicates missing or incorrect authentication.
- HTTP 404 indicates an unknown path or chunk, or an absent stored result.
- HTTP 405 rejects a method not allowed for a known path; read the `Allow` header.

### Read-only checks with curl

Set the reachable server URL and operator-provided credentials. In CI, supply
credentials through the job's secret mechanism rather than committing them.
Omit `--user "$AUTH"` from commands when authentication is disabled.

```sh
BASE='http://localhost:8000'
AUTH='user:password'

curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/"
curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/prompt/analyst"
curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/schema/input"
curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/schema/result"
curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/chunks"

# Replace this example with a filename returned by /chunks.
CHUNK='batch_001/001.json'  # Use a source_chunk listed by this server.
curl --fail-with-body --silent --show-error --user "$AUTH" \
  "$BASE/chunk/$CHUNK" --output chunk.json
sha256sum chunk.json
```

`--fail-with-body` makes HTTP errors produce a nonzero curl exit status while
retaining the response body. A CI job should check exit statuses and validate
JSON against the supplied schemas, rather than assuming a response is valid.

### Submit and verify a real result

Use an authorized, schema-conforming `result.json` for the selected chunk.
The upload changes server state; the verification and export requests do not.

```sh
curl --fail-with-body --silent --show-error --user "$AUTH" \
  -H 'Content-Type: application/json' --data-binary @result.json "$BASE/result/$CHUNK"
curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/result/$CHUNK"
curl --fail-with-body --silent --show-error --user "$AUTH" \
  "$BASE/export" --output results.zip
```

### Read-only Python check

This Python 3 example discovers chunks without uploading. Set `BASE_URL` to
this server's address and optionally supply `AI_AUTH` through the CI secret
environment. Authentication, HTTP, and JSON errors make the script fail;
this checks discovery only, not full schema compliance.

```python
import base64
import json
import os
from urllib.request import Request, urlopen

base = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
headers = {}
credentials = os.environ.get("AI_AUTH")
if credentials:
    token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    headers["Authorization"] = "Basic " + token
request = Request(base + "/chunks", headers=headers)
with urlopen(request, timeout=10) as response:
    listing = json.load(response)
if not isinstance(listing, dict) or not isinstance(listing.get("run_id"), str):
    raise ValueError("Invalid chunk listing identity")
chunks = listing.get("chunks")
if not isinstance(chunks, list) or not all(isinstance(path, str) for path in chunks):
    raise ValueError("Invalid chunk URLs")
print(json.dumps(listing, indent=2))
```

### Authentication and network safety

When authentication is enabled, every endpoint requires HTTP Basic credentials,
including this guide. Use credentials supplied by the operator; do not guess
or disclose them. Browsers can use the HTTP login prompt.
Plain HTTP does not encrypt credentials or analysis data. Use a trusted network
or an operator-provided HTTPS endpoint. Without authentication, access is unrestricted.
