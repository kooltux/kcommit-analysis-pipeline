# Optional AI analysis workflow

AI assessment is advisory. The ordinary pipeline runs stages 00–07 and does not
require an AI service. Stage 08 prepares an independent work package from the
stage 04 prefilter-kept commits, before scoring and postfiltering. It does not
change scores, priorities, or cherry-pick test results.

## Prepare

Run the ordinary pipeline first, then use:

```sh
python3 kcommit_pipeline.py run --config product.json --stage 8
```

Alternatively, `run --config product.json --ai` includes Stage 08 in the
full run. The `ai.chunk_size` setting is the positive number of commits per
chunk (default 100); `ai.prompt_path` selects an optional prompt override.
The bundled result schema is `configs/ai/ai_analysis_result_schema.json`.
Stage 08 writes numbered JSON chunks, input and output schemas, a prompt, a
checksummed bundle manifest, and `serve_ai.pyz` to the configured output
directory. An empty prefilter set produces an empty chunk. Keep these files
together until importing the returned results.

## Analyze remotely

Copy `serve_ai.pyz` to the analysis machine and start it with Python 3:

```sh
python3 serve_ai.pyz 8001 127.0.0.1
```

The default listener is loopback-only. Exposing this service on a network
requires your own access control: the server has no authentication and accepts
result uploads. Use `GET /prompt`, `GET /schema/input`, `GET /schema/output`,
`GET /chunks`, and `GET /chunk/<name>` to inspect the work. Return one schema-
conforming result document per chunk using `PUT /result/<name>`. Results may
be partial; a complete result must cover every source SHA. `GET /result/<name>`
retrieves an uploaded result. `GET /export` returns a ZIP containing the source
manifest, chunks, and any accepted results. Keep the ZIP for the import step.

Do not assume mitigation settings or infer CVE IDs that are not supported by
source commits. Risk value `none` must be used alone; CVE probabilities align
positionally with CVE IDs. Human review is required before backporting.

## Import

Transfer the exported ZIP back to the pipeline machine and run:

```sh
python3 kcommit_pipeline.py ai-import --config product.json --results-bundle results.zip
```

The importer checks manifest and schema identities, exact chunk bytes, source
SHA membership, and result fields before writing a result sidecar. The report
path then decorates report-only commit copies with `ai_analysis` when the
sidecar `run_id` matches the current bundle. The relevant and filtered JSON
reports and commit-detail shards can carry this advisory object; the HTML
commit detail pane shows an advisory card. Existing scoring caches and ranking
remain unchanged. A later Stage 08 run with a different identity makes the
old result sidecar inapplicable. A missing result for a commit means no AI
assessment was returned; it must not be interpreted as a negative finding.

## QA before committing

Run `./run_tests` from the repository root and review any changes to the
HTML report, JSON exports, and imported sidecar. If tests cannot be executed,
do not commit. The `--stage 8 --force` path can remove Stage 08 outputs; keep
a copy of the exported result ZIP until import has been verified.
