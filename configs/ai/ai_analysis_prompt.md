# AI Analysis Prompt for Linux kernel commits

Analyze commits that passed the pipeline prefilter for product relevance and
backporting. Treat recommendations as advisory: a human must review them.

## Contract

1. Read `GET /prompt`, `GET /schema/input`, and `GET /schema/output`. The schemas
   define the input and output fields and are authoritative over examples.
2. Read `GET /chunks` and fetch each listed `/chunk/<name>`. Analyze each commit
   independently; these are prefilter-kept commits, not pipeline-scored results.
3. Create one result JSON object per input chunk, following `/schema/output`.
   Copy `run_id`, `source_chunk`, `input_schema_checksum`, and
   `output_schema_checksum` from the chunk. Set `input_checksum` to the SHA-256
   of the exact chunk response bytes. Keep `total_commits` unchanged; set
   `analyzed_commits` to the number of SHA-keyed entries in `results`. Use the
   full 40-character commit SHA as each key.
4. `PUT /result/<same chunk filename>` with the result JSON. Use
   `analysis_status: "partial"` if any commit has not been analyzed. Retrieve
   accepted results with `GET /result/<name>`. Once done, download `/export`
   and return the ZIP to the pipeline machine for `ai-import`.

## Assessment policy

- Use the commit message, changed paths, annotations and product-evidence tags
  present in the source chunk. Do not infer pipeline scores or clean cherry-picks.
- Treat `meta` flags as hints, not proof of a vulnerability or backport need.
  Assess whether the changed path and code are actually relevant to the product.
- Never invent CVE identifiers. List only IDs supported by the source commit
  message; leave both CVE arrays empty otherwise. Probabilities align by index
  with the CVE IDs and are percentages from 0 to 100.
- Estimate backport effort from size and stated dependencies. A line count alone
  cannot establish feasibility; do not claim to have executed a cherry-pick.
- If product configuration, mitigation, exposure or code behavior is not present
  in the input, state the uncertainty. Do not assume Secure Boot, SELinux, DAC,
  seccomp, namespaces, or locked debug interfaces are enabled for every product.
- Keep rationales concise and evidence-based. Do not alter source metadata,
  pipeline scores, rankings, or cherry-pickability. `none` must be the sole
  value in `ai_risks_if_not_backported` when there are no identified risks.
- Use `maybe` where the evidence cannot justify a definite recommendation.
  A result marked complete must cover every SHA in the input chunk.

The output schema defines `ai_is_security_fix`, `ai_backport_recommendation`,
and all other required assessment fields.
