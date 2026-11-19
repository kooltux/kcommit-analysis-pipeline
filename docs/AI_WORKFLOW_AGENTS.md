# AI workflow agent handoff

## Distribution

Supply each agent its own Markdown prompt plus the same freshly captured
`/v2/api` catalog and complete `/` entry-guide context from the delivered package.

- Parent agent: `AI_TOP_WORKFLOW_PROMPT.md`.
- Child agent: `AI_GROUP_WORKFLOW_PROMPT.md`.

Neither agent should require the other's conversation or prompt. Both require
connection settings appropriate to the workflow environment, not invented URLs.
The child has preconfigured model and API settings; its only dynamic input is
`group_id`. Do not put credentials in documents or model context.

## Authority and checks

The served catalog defines executable methods, paths, parameters, bodies,
responses and authentication. Served role prompts/schemas define model behavior
and document fields. Workflow prompts define orchestration, not another API.

Do not mix documents from different generated packages. The catalog must expose
GET /v2/plan, GET /v2/group/<group_id>, POST /v2/result/<group_id>, and optional
POST /v2/validate/<group_id>. On mismatch, report it rather than substituting old
routes. An agent without network access may check supplied documents, but must
not claim to have checked the live server.

Use generic AI terminology in workflow names and artifacts. Workflow agents do
not configure the server or need its schema-acceptance configuration.

## Delivery gate

Distribute the pack only after generated-package HTTP testing confirms that
catalog, guide, schemas, group retrieval and submission agree. Source-only tests
cannot establish deployed behavior. Keep actual QA results separate from plans.
The user confirmed full QA passing after schema-policy completion on 2026-11-19.
The handoff is ready for workflow design when paired with the matching current
catalog and guide. Later changes, including release metadata, require fresh QA
before commit; earlier generated packages must be rebuilt to carry the new version.
