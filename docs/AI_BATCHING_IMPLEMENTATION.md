# AI batching implementation status

The approved design uses `ai.chunk_size` for commits per chunk and
`ai.batch_size` for chunks per batch. The batch-size default is 10.
Both settings require positive integers; booleans are not valid sizes.

Configuration validation, batch directories, canonical chunk identities,
manifest metadata, server routes, nested uploads/export/import, prompts and
regression tests are implemented. See AI_ANALYSIS.md for usage.
The user reported the full test suite passing on 2026-10-15 after the front-page fix.
The approved release is v21.0.0 because generated paths and chunk identities change.
Release metadata edits require a fresh version-consistency and full-suite run.
Staging, committing and tagging require their separate confirmations; never push.
