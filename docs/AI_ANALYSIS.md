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

## Server front page

Set `ai.front_page_path` in `configs/conf.d/07_ai.json` to an external UTF-8
Markdown file. The shipped value is `${CONFIGDIR}/ai/ai_server_front_page.md`.
Stage 08 validates the file, copies it to `output/ai_server_front_page.md`,
and embeds it in `serve_ai.pyz`; missing, empty, or invalid UTF-8 files fail
preparation before outputs are modified. The portable bundle needs no access
to the original config directory. Regenerate it after editing the Markdown.

`GET /` and `GET /README.md` serve identical raw Markdown with
`Content-Type: text/markdown; charset=utf-8`. They use the same authentication
and access logging as other endpoints. Rendering HTML is not required; this
keeps the zipapp dependency-free. The guide explains the purpose, workflow,
endpoints, result requirements, and network safety without replacing `/prompt`.
The guide is presentation-only and does not change analysis run identities.

## Analyze remotely

Copy `serve_ai.pyz` to the analysis machine and start it with Python 3:

```sh
python3 serve_ai.pyz -l ./ai-server.log --auth 'user:password'
```

By default, the server detaches into the background and listens on loopback
(`127.0.0.1:8000`). Daemon mode requires explicit `-l PATH` or `--log-file PATH`.
It prints its PID, actual listening address, and log
location. Stop it with `kill PID` using that printed PID. SIGTERM and SIGINT
close the server cleanly. Positional `port host` arguments remain supported;
port 0 selects an available port. The old default was `127.0.0.1:8001` in the
foreground. Regenerate existing bundles with Stage 08 to receive the new code.

`-d`, `--debug`, and `--no-daemon` are aliases for one foreground option;
`--debug` does not add verbose logging. Background mode requires Unix.
For foreground operation without a log file, run `./serve_ai.pyz -d`; all logs
go to stderr. To select file-only logging instead:

```sh
python3 serve_ai.pyz -d --log-file "$HOME/kcommit-analyze-ai-server.log" \
  --auth 'user:password' 8000 127.0.0.1
curl --user 'user:password' http://localhost:8000/chunks
```

There is no default log-file path. `-l PATH` and `--log-file PATH` are aliases:
when supplied, logs append only to that file, regardless of foreground or daemon
mode. An unwritable file causes startup failure with no fallback to stderr.
Without this option, foreground mode logs only to stderr; daemon mode rejects
the invocation before detaching. New log files use mode 0600. Startup diagnostics
may still appear on stderr when startup fails. Startup and shutdown lines are
marked `SERVER`. Foreground startup also prints one flushed summary to stdout,
independent of log selection, showing debug mode, PID, bind address, log location
(or stderr), and the connection URL. The daemon's startup summary includes its URL.
The actual bound port is used; for `0.0.0.0`, the URL uses local `127.0.0.1` while
retaining the wildcard bind address. No credentials appear in these summaries.
Each request emits one completion line with UTC time, client, escaped method/path,
status, duration in milliseconds, and a safe reason. Authentication failures,
invalid uploads, unknown paths, unsupported methods, and internal errors are
logged without duplicate default messages. Timeouts and disconnects are logged
once; status is `-` if no response was started, otherwise the attempted status.
Idle connections closed without a request do not produce access lines. Query
strings, request bodies, credentials, and exception text are omitted. HTTP only;
no TLS or proxy handling is added:

```text
2026-10-09T00:10:03Z client=127.0.0.1 method="GET" path="/chunks" status=200 duration_ms=2 reason=ok
2026-10-09T00:10:05Z client=127.0.0.1 method="PUT" path="/result/1.json" status=400 duration_ms=1 reason=invalid_result
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
