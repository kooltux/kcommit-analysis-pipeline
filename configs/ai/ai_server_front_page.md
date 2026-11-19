# Kernel commit analysis: two APIs

## 1. For human readers

This server shares selected kernel commit evidence and accepts validated advisory
findings. It does not run AI models, approve backports, or change pipeline scores.
Human reviewers, AI clients and CI jobs start here and choose one live catalog:

- [GET /v1/api](/v1/api): source selections delivered in packaged chunks.
- [GET /v2/api](/v2/api): source selections delivered through bounded cached plans.

These are the only API-definition endpoints. Bare `/v1` and `/v2` are not catalogs.
Unversioned API paths return HTTP 404; there are no aliases or redirects. This
readable guide at `/` is the only unversioned document. Each catalog is generated
from the executable route registry rather than a second endpoint table.

Each API is self-contained. Use its `/contract`, `/prompt/<name>`, `/schema/<name>`,
`/version`, validation, result and export URLs. For example, `/v1/prompt/analyst`
and `/v2/prompt/analyst` provide the same role instructions and effective schemas.
Stay within the chosen prefix. A contract checksum/byte count identifies the exact
served document, including schemas appended to complete role prompts. Original
archive schema assets are provenance, not replacements for effective HTTP schemas.

### Source selection

For v1, retrieve `/v1/chunks`, preserve the selected entries and fetch each entry's
`url` directly. The listing supports `limit` and `offset`: absent/zero limit is
unlimited. Both values must be nonnegative integers supplied once. Unknown,
repeated, empty or malformed parameters return HTTP 400 rather than expanding work.

For v2, call `GET /v2/plan`, optionally with positive integer query parameters
`max_commits_per_group`, `max_bytes_per_group`, and testing cap `max_groups`.
Packaged commits are implicit. Iterate `groups` and pass only `group_id` to a child.
`total_groups`, `returned_groups`, `limited` distinguish a capped test subset.
GET `/v2/group/<group_id>` returns the complete source input; durable definitions
survive plan-cache eviction and restart. Unknown groups return HTTP 404.
Oversized commits are rejected, not truncated. Source-byte limits do not establish
model token/context feasibility. Old POST planning and plan-ID paths are removed.

Both delivery forms return exactly `run_id` and `commits`. The run identity belongs
to the analysis, not a chunk or plan. Changing groups does not change accepted
records. Never expand an operator's restricted selection automatically.

## 2. For AI clients

### Context and task

The operator/orchestrator performs HTTP requests and supplies trusted sources,
complete prompts and effective schemas to the models. LLMs return documents; they
do not perform server operations. Missing findings are not negative assessments.
Only the CVE expert may use configured research tools to verify candidate IDs
already present in source commit messages. Analyst and Reviewer use supplied evidence.

### Role workflow

1. Analyst and CVE expert independently assess the same selected commits. Analyst
   owns non-CVE findings; CVE expert owns supported source-message CVE candidates
   and probabilities. Optional checks use `/validate/role/analyst` or
   `/validate/role/cve` under the chosen API prefix.
2. Reviewer reads original evidence and both specialist documents, recording
   advisory `rv_*` proposals without rewriting specialist values. Its optional
   role check is `/validate/role/reviewer` under the chosen API prefix.
3. Role documents contain exactly `run_id`, `role`, and `results`, keyed by full
   commit SHA. All three submitted documents must cover exactly the same SHAs.
   Other commits remain unassessed. Delivery names and plan/group IDs are not
   envelope fields. Do not emit transport checksums, counts or status.
4. Mechanically assemble exactly `analyst`, `cve`, `reviewer` as role JSON objects.
   There is no fourth final document. V2 submits the entire group once to
   `POST /v2/result/<group_id>`; optionally check at `POST /v2/validate/<group_id>`.
   V1 uses `POST /v1/result` and optional `POST /v1/validate/workflow`.
   Validation gates store nothing. Pre-validation is not a prerequisite.
5. Require HTTP 200 and `status: stored`. The `results` map gives a SHA-256 checksum
   for every accepted SHA. Retrieve exact bytes at `/v2/result/commit/<sha>` or
   `/v1/result/<sha>`. Records contain `run_id`, `commit`, `assessment`.
   Do not apply review recommendations. Reassessment replaces supplied SHAs only;
   v2 requires all SHAs in the identified group and retains other accepted records.

Missing or inconsistent inputs require a failure report to the caller. Never POST
a failure report as an assessment. Schemas are authoritative over examples.

### Using this server

Choose the API prefix first. Read its `/api`, `/contract`, and complete role prompts;
the prompts already embed the effective schemas they read. Append source selections
and prior specialist outputs separately. Catalog method/URL examples alone are not
complete POST requests: follow the separate `request_body` definition.

Export through the API's `/export`: the deterministic ZIP includes original source/
contract provenance and all accepted canonical findings. GET never publishes or
migrates findings. Publication is atomic per SHA, not a whole-batch transaction.
One writer per result root is supported; report publication is not transactional.

## 3. For automation and testing

### HTTP requirements and responses

POST raw JSON with one `Content-Length`, one `Content-Type: application/json`, no
`Transfer-Encoding`, and 1 byte to 10 MiB of body. Each catalog describes request
schemas, limits, path parameters, response schemas and authentication. Resolve
catalog-local fragments within that catalog, and schema links within its prefix.
GET result examples can return 404 until accepted findings exist.

HTTP 400 rejects invalid inputs; HTTP 401 requires valid credentials; HTTP 404
means an absent route/source/group/finding; HTTP 405 rejects a method on an existing
route and supplies `Allow`. Errors are always JSON. Successful JSON and Markdown
can negotiate `Accept: text/plain` without changing bytes. ZIP and errors are not
converted. Validation never corrects values.

HTTP contributions ignore unknown fields at the closed workflow, role-envelope
and per-commit assessment levels before validation. `--strict-schema` rejects
those extras instead. Both APIs and their validation/submission endpoints share
this policy, reported in the catalog's `schema_policy`. Missing fields, invalid
defined values, identities and SHA coverage are never repaired. Stored records
and offline import remain strict. Normal logs record escaped ignored field paths,
not values; explicitly enabling `--save-posts` still captures raw requests.

### Read, validate, submit and export

These examples use v1 only. V2 uses the explicit group paths above; replacing the prefix alone is insufficient.
Do not upload placeholder findings to an operator's server as a connectivity test.

```sh
BASE='http://localhost:8000'
API="$BASE/v1"
AUTH='user:password'
curl --fail-with-body --silent --show-error --user "$AUTH" "$BASE/"
curl --fail-with-body --silent --show-error --user "$AUTH" "$API/api"
curl --fail-with-body --silent --show-error --user "$AUTH" "$API/contract"
curl --fail-with-body --silent --show-error --user "$AUTH" "$API/prompt/analyst"
curl --fail-with-body --silent --show-error --user "$AUTH" "$API/chunks"
curl --fail-with-body --silent --show-error --user "$AUTH" \
  -H 'Content-Type: application/json' --data-binary @contributions.json "$API/validate/workflow"
curl --fail-with-body --silent --show-error --user "$AUTH" \
  -H 'Content-Type: application/json' --data-binary @contributions.json "$API/result"
curl --fail-with-body --silent --show-error --user "$AUTH" "$API/export" --output results.zip
```

Omit `--user` when authentication is disabled. When enabled, normal authentication
applies to both APIs and this guide. Use operator-provided credentials; never guess
or publish secrets. Plain HTTP does not encrypt credentials/evidence: use a trusted
network or HTTPS termination. Without authentication, access is unrestricted.
