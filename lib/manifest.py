"""Pipeline manifest loader — single source of truth for version and metadata."""
import json
import pathlib

_MANIFEST_PATH = pathlib.Path(__file__).parent.parent / 'MANIFEST.json'


def load_manifest():
    """Return the parsed MANIFEST.json dict."""
    return json.loads(_MANIFEST_PATH.read_text(encoding='utf-8'))


VERSION = load_manifest()['version']
