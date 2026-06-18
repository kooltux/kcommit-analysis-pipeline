"""serve_script_gen.py — kcommit-analysis-pipeline v16

Generates a self-contained ``serve_report.pyz`` zipapp.

A zipapp is a ZIP archive that Python can execute directly::

    python serve_report.pyz [PORT [HOST]] [--browse]
    ./serve_report.pyz      [PORT [HOST]] [--browse]   # after chmod +x

The archive contains:

  __main__.py             — HTTP server entry point (pure Python, no payload)
  index.html              — fully inlined HTML report
  commits/<1>/<2>.json    — bucketed commit detail JSON files keyed by full SHA
                            (G.4: at most 256 bucket files across 16 first-level dirs)

At runtime ``__main__.py`` opens the archive via
``zipfile.ZipFile(sys.argv[0])`` and serves files directly from the ZIP
member list — nothing is ever extracted to disk.

Why zipapp instead of an appended-binary-payload .py script:
- Python's tokenizer scans the *entire* .py file before execution;
  binary bytes (null bytes, invalid sequences) cause SyntaxError.
- A ZIP archive is opaque to the tokenizer — Python only parses
  __main__.py, not the other ZIP members.
- No base64 overhead (+0% vs +33%), random-access to individual members,
  and it is a first-class stdlib feature (zipapp, Python 3.5+).

Compression: ZIP_DEFLATED at level 9 (maximum).
  ZIP_LZMA cannot be used: CPython's zipimport (the mechanism that
  launches a .pyz file) only supports STORED and DEFLATED.  LZMA members
  cause a zlib.error at startup even though zipfile itself can read them.
  DEFLATE level 9 is the highest supported compression for a launchable
  zipapp.

Shebang / offset handling:
  The shebang is injected via ``zipapp.create_archive()``, which is the
  only correct way to prepend a shebang — it adjusts the ZIP central-
  directory offsets.  Manual byte-prepending breaks zipimport.

Public API
----------
  generate_serve_script(html_path, commits_root, output_path)

  ``output_path`` should end in ``.pyz`` but is not enforced.
"""
import io
import os
import zipapp
import zipfile

# ---------------------------------------------------------------------------
# __main__.py source — stored as a plain string, written into the ZIP.
# ---------------------------------------------------------------------------

_MAIN_SOURCE = '''\
#!/usr/bin/env python3
"""kcommit-analysis-pipeline — self-contained report server.

This file is the entry point of a zipapp (serve_report.pyz).
All report assets (index.html, commits/**/*.json bucket files) are stored as
members of the same ZIP archive alongside this __main__.py.
No files are extracted to disk at runtime.
"""
import argparse
import http.server
import mimetypes
import sys
import threading
import webbrowser
import zipfile

# ---------------------------------------------------------------------------
# Asset loading — read directly from the ZIP archive
# ---------------------------------------------------------------------------

_ZF    = None   # zipfile.ZipFile, opened once in main()
_NAMES = set()  # member names for fast existence checks


def _open_archive():
    global _ZF, _NAMES
    _ZF    = zipfile.ZipFile(sys.argv[0], \'r\')
    _NAMES = {m.filename for m in _ZF.infolist()}


def _read(name):
    """Return bytes for *name* from the ZIP, or None if not found."""
    name = name.lstrip(\'/\')
    if name in _NAMES:
        return _ZF.read(name)
    return None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = self.path.split(\'?\')[0].rstrip(\'/\')
        if path == \'\' or path == \'/\':
            path = \'/index.html\'

        content = _read(path)
        if content is None:
            self.send_error(404, f\'Not found: {path}\')
            return

        mime, _ = mimetypes.guess_type(path)
        mime = mime or \'application/octet-stream\'
        self.send_response(200)
        self.send_header(\'Content-Type\', mime)
        self.send_header(\'Content-Length\', str(len(content)))
        self.send_header(\'Cache-Control\', \'no-cache\')
        self.end_headers()
        self.wfile.write(content)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser():
    parser = argparse.ArgumentParser(
        prog=\'serve_report.pyz\',
        description=\'Serve a self-contained kcommit-analysis HTML report over HTTP.\',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            \'Examples:\\n\'
            \'  python serve_report.pyz\\n\'
            \'  python serve_report.pyz 9000\\n\'
            \'  python serve_report.pyz 9000 0.0.0.0\\n\'
            \'  python serve_report.pyz --browse\\n\'
            \'  python serve_report.pyz --browse 8080 0.0.0.0\\n\'
        ),
    )
    parser.add_argument(
        \'port\', nargs=\'?\', type=int, default=8000,
        metavar=\'PORT\',
        help=\'TCP port to listen on (default: 8000)\',
    )
    parser.add_argument(
        \'host\', nargs=\'?\', default=\'127.0.0.1\',
        metavar=\'HOST\',
        help=\'Address to bind to (default: 127.0.0.1). Use 0.0.0.0 for all interfaces.\',
    )
    parser.add_argument(
        \'--browse\', action=\'store_true\', default=False,
        help=\'Open the report in the default browser after starting the server.\',
    )
    return parser


def main():
    args = _build_parser().parse_args()

    print(\'[kcap] Opening archive...\', flush=True)
    _open_archive()
    n_assets = len([n for n in _NAMES if n != \'__main__.py\'])
    print(f\'[kcap] {n_assets} assets available.\', flush=True)

    server = http.server.HTTPServer((args.host, args.port), _Handler)
    url    = f\'http://{args.host}:{args.port}/\'
    print(f\'[kcap] Serving report at {url}\', flush=True)
    print(\'[kcap] Press Ctrl+C to stop.\', flush=True)

    if args.browse:
        def _open_browser():
            import time
            time.sleep(0.4)
            if not webbrowser.open(url):
                print(
                    f\'[kcap] Could not open browser. Navigate to {url} manually.\',
                    flush=True,
                )
        threading.Thread(target=_open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(\'\\n[kcap] Stopped.\')
    finally:
        _ZF.close()


if __name__ == \'__main__\':
    main()
'''


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_serve_script(html_path, commits_root, output_path):
    """Write a self-contained serve_report.pyz zipapp to *output_path*.

    Parameters
    ----------
    html_path    : str  Path to the fully-rendered relevant_commits.html
    commits_root : str  Path to the commits/ directory (may not exist if
                        there are no per-commit detail files)
    output_path  : str  Destination path for the generated .pyz archive
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # -- 1. Build ZIP in memory -----------------------------------------------
    # ZIP_DEFLATED at compresslevel=9 (maximum deflate compression).
    # ZIP_LZMA cannot be used: zipimport only supports STORED and DEFLATED.
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        zf.writestr('__main__.py', _MAIN_SOURCE)
        zf.write(html_path, 'index.html')
        if os.path.isdir(commits_root):
            for dirpath, _dirs, filenames in os.walk(commits_root):
                for fname in filenames:
                    if not fname.endswith('.json'):
                        continue
                    abs_path = os.path.join(dirpath, fname)
                    rel_path = os.path.relpath(abs_path,
                                               os.path.dirname(commits_root))
                    zf.write(abs_path, rel_path)
    zip_buf.seek(0)

    # -- 2. Inject shebang via zipapp.create_archive() ------------------------
    # This is the only correct way to prepend a shebang: zipapp adjusts the
    # ZIP central-directory offsets so that zipimport can still locate all
    # records.  Manual byte-prepending breaks offset calculations.
    out_buf = io.BytesIO()
    zipapp.create_archive(
        zip_buf,
        target=out_buf,
        interpreter='/usr/bin/env python3',
    )

    # -- 3. Write to disk -----------------------------------------------------
    with open(output_path, 'wb') as fh:
        fh.write(out_buf.getvalue())

    # -- 4. Make executable on POSIX ------------------------------------------
    try:
        import stat
        st = os.stat(output_path)
        os.chmod(output_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP)
    except OSError:
        pass

    # -- 5. Stats -------------------------------------------------------------
    total_kb = os.path.getsize(output_path) / 1024
    raw_kb   = (os.path.getsize(html_path) + _raw_size(commits_root)) / 1024
    ratio    = (1 - (total_kb / max(0.001, raw_kb))) * 100

    import logging
    logging.info(
        'serve_report.pyz written: %.1f KB raw -> %.1f KB compressed (%.0f%% reduction) | %s',
        raw_kb, total_kb, ratio, output_path,
    )
    return {
        'output_path':   output_path,
        'raw_kb':        round(raw_kb, 1),
        'compressed_kb': round(total_kb, 1),
        'ratio_pct':     round(ratio, 1),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _raw_size(commits_root):
    """Return total byte size of all .json files under commits_root."""
    total = 0
    if os.path.isdir(commits_root):
        for dirpath, _dirs, filenames in os.walk(commits_root):
            for fname in filenames:
                if fname.endswith('.json'):
                    total += os.path.getsize(os.path.join(dirpath, fname))
    return total
