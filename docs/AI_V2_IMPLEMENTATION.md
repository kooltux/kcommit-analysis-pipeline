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

This foundation does not yet install the new HTTP routes. Route integration,
strict-schema CLI handling, documentation replacement and HTTP regression migration
remain pending; do not describe the target interface as delivered until those
changes and integrated QA are complete. No compatibility aliases are planned.
