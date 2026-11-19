# AI v2 QA status and regression migration

The first full QA run after route integration reported 43 failures and 1958
passes. Most failed calls targeted removed v2 routes; receipt tests sometimes
hashed HTTP error bodies instead of records. This was an incomplete test-client
migration, not evidence that those checks could safely be removed.

Regression clients now plan actual groups, validate/submit at group-scoped paths,
and retrieve records at /v2/result/commit/<sha>. Receipt checks require HTTP 200
before digest comparison. Partial reassessment uses complete single-commit groups
and still verifies that unrelated stored records remain unchanged. Arbitrary
noncontiguous selections in import/report tests are submitted as separate complete
single-commit groups, with all three roles present in each request.

The test-only ai_http_helpers module does not add production compatibility routes.
Existing invalid-input tests still require rejection and no publication. Contract
checks retain authentication, schema and exact-byte assertions. Removed routes
remain covered by explicit rejection cases.

The smoke tool retains v1 empty-selection acceptance. For v2, empty sources have
no groups; nonempty groups reject empty coverage. Discovery compares all planned
source membership against the original v1 source documents, including duplicate
and omitted-commit detection. These checks run only on its temporary package copy.

After regression migration, the user reported all 2001 tests passing on
2026-11-19. This is a user-run result, not an independently executed assistant run.

The subsequent schema-policy change adds default extra-field filtering and strict
rejection mode, without changing canonical storage/import checks. Existing tests
that specifically require extra-field rejection explicitly select strict mode.
New HTTP tests cover both APIs and both modes, role/combined gate parity, known
field/identity/coverage errors, receipt equality and strict persisted-record reads.

On 2026-11-19 the user subsequently confirmed QA passing after the schema-policy
patch. No exact count or fresh log was supplied for that run. This clears the
functional QA gate on the basis of a user report, not an independent assistant run.

The v21.6.0 metadata/release-documentation update follows that pass and requires
another ./runtests run before commit. Do not stage or commit without approval.
Publish workflow prompts only with the matching freshly generated API catalog
and complete entry-guide context; version changes do not update existing packages.
