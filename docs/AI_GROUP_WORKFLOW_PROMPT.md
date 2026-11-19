# Design the AI group-analysis subworkflow

Use the separately supplied full API v2 catalog and entry-guide context as the
authority for exact payloads and schemas. Design a self-contained child; no parent
workflow conversation is needed. Use generic AI names throughout.

## Input and configuration

Only dynamic input: {"group_id":"<group ID>"}. Preconfigure API URL/authentication,
three models and permitted research tools. The caller supplies no plan_id,
commit list, source evidence or role prompts. Never include API credentials in
model context.

## Node sequence

1. GET /v2/group/<group_id>. Preserve the complete run_id/commits document,
   including product evidence and every other packaged source field.
2. Fetch /v2/prompt/analyst, /v2/prompt/cve, /v2/prompt/reviewer and corresponding
   /v2/schema/analyst, /v2/schema/cve, /v2/schema/reviewer. Use complete prompts;
   configure structured model output from schemas when supported. Prompts already
   embed effective schemas: avoid needlessly duplicating them in model context.
3. Call Analyst and CVE expert independently, each with its own role prompt and
   the same original group evidence. Only CVE expert may use research tools,
   within its instructions. Each returns a JSON role document with run_id, role,
   results covering exactly every group SHA. Role strings are analyst and cve.
4. Call Reviewer with its prompt, original evidence and both complete specialist
   JSON outputs. Its role string is reviewer. It produces advisory findings,
   not rewritten specialist documents.
5. Mechanically construct one object whose analyst, cve, reviewer properties
   contain the corresponding complete JSON objects, not JSON-encoded strings.
   Preserve run_id and specialist values. Add no group_id, plan_id, counts,
   status or checksums. Do not use a fourth LLM to merge documents or apply
   Reviewer proposals. /v2/schema/workflow describes this combined body; it is
   not an executable workflow. Fetch it only if useful for assembly configuration.
6. POST that combined body once to /v2/result/<group_id>, application/json. Include
   all three roles for all group commits. Normally skip optional /validate calls.
   Do not post separately per role or per commit.
7. Require HTTP 200 and status stored. Return the server's run_id/results checksum
   receipt, associated with the input group_id.

On fetch/model/JSON/submission failure return an explicit group-associated failure,
never a fabricated stored result. Preserve outputs in execution history where
possible. Do not invent findings or introduce an automatic repair/restart loop.

The child does not plan or iterate groups, export results, or configure the server.
Reviewer waits for both specialists; submission waits for all three role documents.
Fetches independent of one another may run in parallel.

Check required routes against the supplied catalog before wiring; report mismatches
rather than silently substituting old paths. Do not claim live testing without
network access. Deliver the node sequence and exact source/role/Reviewer/body/
receipt mappings, configured inputs and failure paths.
