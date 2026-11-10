# Test runner behaviour

`./run_tests [pytest options]` is a thin wrapper around `python3 -m pytest`.
It first changes into the repository directory, then supplies
`-c ./setup.cfg --confcutdir=.` to select the local configuration and bound
conftest discovery. This avoids upward discovery into parent autofs directories.
No positional test directory is forced, so explicit test selections still work.

When `pytest-xdist` is available, tests run in parallel by default with
`--color=<yes|no> -n logical`, one worker per logical CPU. Color is enabled when
stdout is a terminal. `-n auto` only counts physical cores, which is slower for
this I/O-bound suite. Additional arguments are forwarded unchanged; the script
does not interpret them. Default options come first, so explicit configuration,
conftest-boundary, color and worker-count options supplied later take precedence:

```bash
./run_tests                         # all logical CPUs
./run_tests -n 4                    # four workers
./run_tests -n 0 --pdb              # serial run, needed for interactive debugging
./run_tests --color=no tests/x.py   # explicit --color wins too
```

Interactive debugging (`--pdb`, `-s`, `--trace`) does not work with parallel workers:
add `-n 0`. The script does not detect these options on purpose.

The default `-n logical` is only added when `pytest-xdist` can be imported by
`python3`. Without it the tests run serially, the log says so
(`run_tests: tests run by default serially (pytest-xdist not available)`) and an
explicit `-n` of yours is rejected by pytest as an unknown option.

`pytest-xdist[psutil]` is listed in `requirements-dev.txt`. Tests must stay
independent: use `tmp_path`, `monkeypatch` and port 0, never fixed paths or ports.

## Output and exit status

Pytest runs exactly once per invocation, whether it passes or fails. Its complete
output is saved uncolored to `$KCAP_TEST_LOG` (default
`/tmp/kcommit-analysis-pipeline.log`) and copied to the clipboard when `xclip` and a
display are available; the exit status is returned unchanged. There is no automatic
retry.

The log (and the clipboard copy) starts with the invocation: the command line as typed,
the resulting pytest command line and the working directory, all shell-quoted. The same
lines are printed on the terminal.

## Tests

`tests/test_run_tests_script.py` checks, with a stubbed `python3`, the repository-local
`-c ./setup.cfg --confcutdir=.` defaults and explicit caller overrides, the
`-n logical` default, the serial fallback without `pytest-xdist`, unchanged argument
forwarding, the single run, logging, clipboard copying, invocation lines and
exit-status preservation.
