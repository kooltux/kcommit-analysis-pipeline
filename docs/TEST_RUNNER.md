# Test runner behaviour

`./run_tests [pytest options]` is a single script, a thin wrapper around
`python3 -m pytest`. It runs the tests in parallel by default: it starts pytest with
`--color=<auto> -n logical`, i.e. one `pytest-xdist` worker per logical CPU (`-n auto`
only counts physical cores, which is slower for this I/O-bound suite). All other
arguments are forwarded unchanged and the script does not interpret them. The default
options come first, so yours win:

```bash
./run_tests                         # all logical CPUs
./run_tests -n 4                    # four workers
./run_tests -n 0 --pdb              # serial run, needed for interactive debugging
./run_tests --color=no tests/x.py   # explicit --color wins too
```

Interactive debugging (`--pdb`, `-s`, `--trace`) does not work with parallel workers:
add `-n 0`. The script does not detect these options on purpose.

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

`tests/test_run_tests_script.py` checks, with a stubbed `python3`, the `-n logical`
default, argument forwarding (a later `-n` wins), the single run, the log, the
clipboard copy, the invocation lines and the exit status.
