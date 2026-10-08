# Kernel commit analysis API

## 1. For human readers

This server shares kernel commit analysis inputs and accepts validated results.
It serves instructions, JSON schemas, and source chunks, stores assessments,
and provides an export ZIP. It does not perform the analysis itself.

This reference is for human reviewers, AI clients, and CI jobs. Assessment
instructions live in `/prompt`; exact data contracts live in the schemas.

### Access and scope

GET requests are read-only. PUT replaces the stored result for a chunk.
When authentication is enabled, use the operator-provided credentials; browsers
can use the HTTP login prompt. Assessments remain advisory. This server is an
exchange interface, not an autonomous reviewer or a backport approval system.

### API overview

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` or `/README.md` | This page as UTF-8 Markdown |
| GET | `/prompt` | Assessment instructions |
| GET | `/schema/input` | Source chunk schema |
| GET | `/schema/output` | Required result schema |
| GET | `/chunks` | Run identity and available chunk URLs |
| GET | `/chunk/<name>` | One source chunk; use names returned by `/chunks` |
| PUT | `/result/<name>` | Validate and save a result for a known chunk |
| GET | `/result/<name>` | Retrieve an accepted result; 404 if absent |
| GET | `/export` | ZIP of manifest, source chunks, and accepted results |

## 2. For AI clients

### Context and task

You are the analysis client, not the server. Your task is to assess the supplied
kernel commits under the instructions retrieved from `/prompt`, using available
evidence, and return results conforming to `/schema/output`. This API guide
explains access and submission; it does not replace those assessment instructions.
Do not infer that a missing result is a negative assessment.

### Using this server

1. Retrieve `/prompt`, `/schema/input`, and `/schema/output` before analyzing.
2. Retrieve `/chunks` and use its run ID and listed URLs exactly. Do not guess
   chunk filenames or assume a numbering width.
3. Download a listed chunk and preserve its original bytes for checksum matching.
   Assess only commits from that chunk using the prompt and supported evidence.
4. Build a schema-conforming result. Use partial status if only a subset was
   assessed; do not fabricate results or unsupported CVE IDs.
5. When authorized, submit to `PUT /result/<name>` for that source chunk.
6. Check for HTTP 200 and `{"status":"ok"}`, then GET the same result URL to
   verify acceptance. A rejected upload is not a completed submission.

### Result contract

- Follow `/schema/output` exactly, including field names and types.
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
curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/schema/output"
curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/chunks"

# Replace this example with a filename returned by /chunks.
CHUNK='1.json'
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
