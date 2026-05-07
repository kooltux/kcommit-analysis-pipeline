"""Tests for lib.html_report — generate_html_report, I.5 RuntimeError guard."""
import os
import pytest

from lib.html_report import generate_html_report


def _make_tpl_dir(tmp_path, body_marker='__BODY__'):
    tpl_dir = tmp_path / 'html'
    tpl_dir.mkdir(exist_ok=True)
    (tpl_dir / 'report.html').write_text(
        f'<html><head></head><body>{body_marker}</body></html>')
    (tpl_dir / 'summary.css').write_text('body { margin: 0; }')
    (tpl_dir / 'summary.js').write_text('console.log("ok");')
    return str(tpl_dir)


def _out(tmp_path, name='out.html'):
    return str(tmp_path / name)


# ── I.5: RuntimeError when __BODY__ marker absent from template ──────────────
def test_missing_template_raises(tmp_path):
    """report.html present but without __BODY__ marker → RuntimeError (I.5 guard)."""
    tpl_dir = tmp_path / 'html'
    tpl_dir.mkdir()
    (tpl_dir / 'report.html').write_text('<html><body>NO MARKER HERE</body></html>')
    (tpl_dir / 'summary.css').write_text('')
    (tpl_dir / 'summary.js').write_text('')
    with pytest.raises(RuntimeError, match='__BODY__'):
        generate_html_report([], {}, {}, _out(tmp_path),
                             templates_dir=str(tpl_dir))


def test_template_missing_body_marker_raises(tmp_path):
    """Alias: same I.5 guard — explicit no-marker template."""
    tpl_dir = tmp_path / 'html'
    tpl_dir.mkdir()
    (tpl_dir / 'report.html').write_text('<html><body>WRONG</body></html>')
    (tpl_dir / 'summary.css').write_text('')
    (tpl_dir / 'summary.js').write_text('')
    with pytest.raises(RuntimeError, match='__BODY__'):
        generate_html_report([], {}, {}, _out(tmp_path),
                             templates_dir=str(tpl_dir))


# ── Happy path ────────────────────────────────────────────────────────────────
def test_generate_html_report_empty_commits(tmp_path):
    tpl_dir = _make_tpl_dir(tmp_path)
    out = _out(tmp_path)
    generate_html_report([], {}, {}, out, templates_dir=tpl_dir)
    assert os.path.isfile(out)
    assert '<html' in open(out).read()


def test_generate_html_report_with_commits(tmp_path):
    tpl_dir = _make_tpl_dir(tmp_path)
    commits = [
        {'commit': 'abc123', 'subject': 'net: fix skb leak',
         'score': 80, 'matched_profiles': ['networking'],
         'files': ['drivers/net/core.c'], '_filter_action': 'keep'},
    ]
    out = _out(tmp_path)
    generate_html_report(commits, {}, {}, out, templates_dir=tpl_dir)
    content = open(out).read()
    assert 'abc123' in content or 'net: fix skb leak' in content


def test_generate_html_report_title_in_output(tmp_path):
    tpl_dir = _make_tpl_dir(tmp_path)
    out = _out(tmp_path)
    generate_html_report([], {}, {}, out, title='My Custom Title',
                         templates_dir=tpl_dir)
    assert 'My Custom Title' in open(out).read()
