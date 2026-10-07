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
python3 serve_ai.pyz --auth 'user:password'
```

By default, the server detaches into the background and listens on all IPv4
interfaces (`0.0.0.0:8000`). It prints its PID, actual listening address, and log
location. Stop it with `kill PID` using that printed PID. SIGTERM and SIGINT
close the server cleanly. Positional `port host` arguments remain supported;
port 0 selects an available port. The old default was `127.0.0.1:8001` in the
foreground. Regenerate existing bundles with Stage 08 to receive the new code.

`-d`, `--debug`, and `--no-daemon` are aliases for one foreground option;
`--debug` does not add verbose logging. Background mode requires Unix.
For loopback-only foreground operation with a writable log:

```sh
python3 serve_ai.pyz -d --log-file "$HOME/kcommit-analyze-ai-server.log" \
  --auth 'user:password' 8000 127.0.0.1
curl --user 'user:password' http://localhost:8000/chunks
```

Logs append to `/var/log/kcommit-analyze-ai-server.log` by default. If this
cannot be opened, startup fails with a request to choose `--log-file PATH`;
do not run as root merely to use the default. Provision a writable log file
for the service account or select another path. New log files use mode 0600.
Foreground mode also emits logs to stderr. Startup and shutdown lines are
marked `SERVER`; each HTTP response emits one compact access line, including
rejections, with a UTC timestamp, client address, JSON-escaped method/path,
and response status. Query strings, request bodies, and credentials are omitted:

```text
2026-10-07T18:55:12Z 192.168.1.20 "GET" "/chunks" 200
2026-10-07T18:55:15Z 192.168.1.20 "PUT" "/result/1.json" 401
```

`--auth USER:PASSWORD` protects all endpoints using HTTP Basic authentication.
Both parts must be nonempty; passwords may contain colons. Missing, malformed,
or incorrect credentials receive a 401 challenge before endpoint processing.
Clients that support URL credentials may use `http://user:password@host:8000/`;
prefer an explicit client authentication option, and use the browser's login
prompt rather than relying on credential-bearing URLs. Special URL characters
require percent-encoding. Command-line credentials can appear in shell history
and process listings. Basic authentication is not encryption: plain HTTP exposes
credentials and data to interception. Use only on a trusted network or behind
TLS termination. Omitting `--auth` leaves all endpoints unauthenticated and
produces a startup warning. This is minimal shared-password access control,
not a production-hardened public web service. Connections have a 10-second
socket timeout; the server processes requests serially.

Use `GET /prompt`, `GET /schema/input`, `GET /schema/output`,
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
