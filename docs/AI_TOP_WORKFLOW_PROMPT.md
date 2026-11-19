# Design the top-level AI analysis workflow

Use the separately supplied full API v2 catalog and entry-guide context as the
authority for exact API details. Design only the parent workflow. An existing
child independently analyzes one group. Use generic AI names throughout.

## Configuration

Preconfigure API base URL/authentication and child workflow reference. Allow
optional positive integers max_commits_per_group, max_bytes_per_group, max_groups.
Omit unset query parameters; never send empty values. max_groups is a testing cap
on returned groups, not a limit on commits inside each group.

## Node sequence

1. GET /v2/plan with configured query parameters. An illustrative request is
   /v2/plan?max_commits_per_group=10&max_bytes_per_group=262144&max_groups=3.
   These numbers are examples, not model-context sizing recommendations.
2. Iterate sequentially over the returned groups array.
3. Invoke the child once per group with {"group_id":"<groups item group_id>"}.
   Pass no plan_id, commit list, source evidence or role prompts.
4. Collect each child's storage receipt or failure, associated with group_id.
   Return attempted/successful/failed counts and group outcomes. Preserve
   total_groups, returned_groups and limited to distinguish a test subset from
   full coverage. A child invocation is not successful merely because it ran;
   require its successful storage outcome.

Empty groups means no work. A planning failure stops iteration. Keep child
failures visible; do not invent success. No automatic LLM repair loop.

The parent does not fetch role prompts, call models, assemble findings, submit
results again or export. It does not configure the server. Connection/model
settings are preconfigured in the child, not supplied per invocation.

Check required methods and paths against the supplied catalog before wiring.
Report discrepancies; do not invent endpoints or introduce a plan-ID-dependent
child input. Do not claim live testing without actual API access.

Deliver a node diagram, precise groups[*].group_id mapping, configured inputs,
error handling and final outcome structure.
