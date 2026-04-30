import json
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.abspath(os.path.join(_THIS_DIR, os.pardir))
_MANIFEST_PATH = os.path.join(_ROOT_DIR, 'MANIFEST.json')

with open(_MANIFEST_PATH, 'r', encoding='utf-8') as _f:
    MANIFEST = json.load(_f)

VERSION = MANIFEST.get('version', 'v0.0.0')
LIBRARY_DIR = MANIFEST.get('library_dir', 'lib')
SCORING_DIR = MANIFEST.get('scoring_dir', 'configs/scoring')
TEMPLATE_DIR = MANIFEST.get('template_dir', 'configs/templates')
PIPELINE_STAGES = MANIFEST.get('pipeline_stages', [])
NSTAGES = len(PIPELINE_STAGES)
TOOLS = MANIFEST.get('tools', [])


def load_manifest(path=None):
    """Load and return the MANIFEST.json dict.
    If *path* is given, load from that path instead of the default location.
    This function exists for backward compatibility with callers that import it
    explicitly (e.g. ``from lib.manifest import load_manifest``).
    """
    if path is None:
        return dict(MANIFEST)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
