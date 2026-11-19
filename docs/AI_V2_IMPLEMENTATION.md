# AI v2 implementation notes

The approved target is a main workflow using GET /v2/plan and a group-ID-only
subworkflow using GET /v2/group/<group_id>, optional POST /v2/validate/<group_id>,
and one POST /v2/result/<group_id> carrying all three role documents.

## Planner foundation

GroupPlanner implements max_commits_per_group, max_bytes_per_group and optional
max_groups. The last option returns a stable prefix of the complete partition;
responses identify total_groups, returned_groups and limited. Limits must be
positive integers. Source bytes are not model token/context budgets.

Returned group definitions persist under groups/<run_id>/<group_id>.json beneath
the supplied runtime state root. Definitions contain only run identity and SHA
membership, not duplicated source evidence. Reads verify the content-derived ID,
run and source membership, and do not depend on the plan cache.

The runtime now registers GET planning, durable group retrieval, optional group
validation, and direct complete-group submission. Individual records are read
at GET /v2/result/commit/<sha>. Definitions persist under the sibling
<zipapp>.results.planning state root, separately from published findings.

See AI_WORKFLOW_AGENTS.md for the two independent workflow-agent prompts and
required matching catalog/context documents.

## HTTP acceptance policy

Default HTTP handling filters unknown workflow/role/assessment fields using the
selected role property sets, then runs every existing canonical check. Result SHA
keys are never filtered. `--strict-schema` disables filtering and rejects extras.
Both APIs use the same policy for role validation, combined validation and storage.
Defined values are never repaired; persisted-record checks and import stay strict.
The catalog reports the active policy and public GET planning-default names.

The user reported 2001 tests passing after regression migration and subsequently
confirmed QA passing after schema-policy completion on 2026-11-19. The final
count/log was not supplied. The functional handoff gate is cleared by that user
report; release-metadata changes still require fresh QA before commit. See AI_V2_QA.md.
