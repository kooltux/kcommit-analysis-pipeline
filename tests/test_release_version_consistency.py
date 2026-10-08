"""Keep current release metadata synchronized without rewriting historical versions."""
import json
from pathlib import Path
import re


def test_release_version_matches_readme_and_latest_changelog():
    root = Path(__file__).resolve().parents[1]
    version = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))['version']
    readme = (root / 'README.md').read_text(encoding='utf-8')
    changelog = (root / 'CHANGELOG.md').read_text(encoding='utf-8')
    assert re.fullmatch(r'v[0-9]+[.][0-9]+[.][0-9]+', version)
    assert f'Current release: `{version}`' in readme
    releases = re.findall(r'^## (v[0-9]+[.][0-9]+[.][0-9]+)\b', changelog, re.MULTILINE)
    assert releases and releases[0] == version
    assert 'Release version remains unchanged pending QA and version approval.' not in changelog
