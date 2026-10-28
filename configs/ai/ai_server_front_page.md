# Kernel commit analysis API

## 1. For human readers

This server shares kernel commit analysis inputs and accepts validated results.
It serves instructions, JSON schemas, and source chunks, stores assessments,
and provides an export ZIP. It does not perform the analysis itself.

This reference is for human reviewers, AI clients, and CI jobs. Assessment
instructions live in `/prompt`; exact data contracts live in the schemas.

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

GET requests are read-only. PUT and POST replace the stored result for a chunk.
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
This guide explains usage; it does not maintain a second endpoint catalog.

The catalog orders routes by discovery/guide, contract assets, source work,
validation, then results/export. Each entry has a group and order, path-parameter
descriptions/examples, and concrete request examples using this package's IDs.
Role values come from the selected assets or the validation route's role contract.
Example objects contain only `method` and `url`, including concrete path/query
parameters. They contain no curl commands, body filenames, schemas or extra notes.
Read the separate `request_body` contract for POST/PUT payload requirements; the
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

`GET /api/version` reports `tool_version`, captured from the generating tool's
`MANIFEST.json`, with `version_source` and `captured_at` provenance. The version
is embedded in the zipapp, remains unchanged when the repository changes, and
does not require repository access at runtime. It is separate from the input
bundle's `pipeline_version`; normal authentication applies and it is not paginated.

## 2. For AI clients

### Context and task

You are the analysis client, not the server. Your task is to assess the supplied
kernel commits under the instructions retrieved from `/prompt`, using available
evidence, and return results conforming to `/schema/result`. This API guide
explains access and submission; it does not replace those assessment instructions.
Do not infer that a missing result is a negative assessment.

### Using this server

1. Retrieve `/api` and `/contract`, then the listed `/prompt/<role>` and `/schema/<role>` assets.
2. Retrieve the selected batch or chunk listing, preserving any `limit` and
   `offset`. Use its run ID and URLs exactly; do not guess filenames or replace
   a debug subset or single-batch retry with the unrestricted global listing.
3. Download a listed chunk and `/metadata/<name>`. Copy authoritative identity and
   checksum fields from that metadata, never from LLM calculations. Execute Analyst
   and CVE separately, then Reviewer, then Assembler. Preserve specialist/reviewer
   values without applying recommendations. POST each intermediate document to
   `/validate/role/<role>/<name>` and the object containing exactly analyst, cve,
   reviewer and result documents to `/validate/workflow/<name>`. Require HTTP 200
   and `{"status":"valid", ...}` before proceeding. Gates store no results; the
   workflow gate checks cross-role coverage and exact assembly preservation.
4. Build a schema-conforming result. Use partial status if only a subset was
   assessed; do not fabricate results or unsupported CVE IDs.
5. When authorized, submit to `PUT /result/<name>` or `POST /result/<name>`.
   Both validate and atomically replace the result for that source chunk.
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

- PUT bodies must be 1 byte to 10 MiB with a valid `Content-Length` header.
  The curl upload example below supplies that header for a regular file.
- Successful uploads return HTTP 200 and `{"status":"ok"}`.
- HTTP 400 rejects an invalid upload; read the error and correct the submission.
- HTTP 401 indicates missing or incorrect authentication.
- HTTP 404 indicates an unknown path or chunk, or an absent stored result.

### Read-only checks with curl

Set the reachable server URL and operator-provided credentials. In CI, supply
credentials through the job's secret mechanism rather than committing them.
Omit `--user "$AUTH"` from commands when authentication is disabled.

```sh
BASE='http://localhost:8000'
AUTH='user:password'

curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/"
curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/prompt"
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
  -H 'Content-Type: application/json' --upload-file result.json "$BASE/result/$CHUNK"
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
