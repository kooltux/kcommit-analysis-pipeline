"""Current release references stay synchronized without rewriting release history."""
import json
import re
from pathlib import Path
from lib.manifest import VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_runtime_and_current_guides_agree():
    manifest = json.loads((ROOT / 'MANIFEST.json').read_text())
    assert manifest['version'] == VERSION
    assert re.fullmatch(r'v[0-9]+[.][0-9]+[.][0-9]+', VERSION)
    readme = (ROOT / 'README.md').read_text()
    assert re.search(r'Current release: `([^`]+)`', readme).group(1) == VERSION
    guide = (ROOT / 'docs/AI_ANALYSIS.md').read_text()
    assert re.search(r'^Version (v[0-9.]+) exposes', guide, re.M).group(1) == VERSION


def test_current_changelog_heading_matches_manifest():
    headings = re.findall(r'^## (v[0-9]+[.][0-9]+[.][0-9]+) ',
                          (ROOT / 'CHANGELOG.md').read_text(), re.M)
    assert headings and headings[0] == VERSION
    assert headings.count(VERSION) == 1


def test_current_helper_comment_and_qa_example_match_manifest():
    assert '(' + VERSION + ').' in (ROOT / 'lib/commit_sets.py').read_text().splitlines()[1]
    assert 'qa-full-' + VERSION + '.log' in (ROOT / 'docs/AI_ANALYSIS.md').read_text()
