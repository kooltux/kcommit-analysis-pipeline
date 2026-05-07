"""Manifest loader for kcommit-analysis-pipeline.

NSTAGES and STAGE_OUTPUTS are derived from pipeline_stages at load time so
that MANIFEST.json is the single source of truth — no manual sync needed.
"""
import json
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.abspath(os.path.join(_THIS_DIR, os.pardir))
_MANIFEST_PATH = os.path.join(_ROOT_DIR, 'MANIFEST.json')

with open(_MANIFEST_PATH, 'r', encoding='utf-8') as _f:
    MANIFEST = json.load(_f)

VERSION         = MANIFEST.get('version', 'v0.0.0')
LIBRARY_DIR     = MANIFEST.get('library_dir', 'lib')
SCORING_DIR     = MANIFEST.get('scoring_dir', 'configs/scoring')
TEMPLATE_DIR    = MANIFEST.get('template_dir', 'configs/templates')
PIPELINE_STAGES = MANIFEST.get('pipeline_stages', [])
TOOLS           = MANIFEST.get('tools', [])

# Derived — never hardcode these; edit MANIFEST.json instead.
NSTAGES      = len(PIPELINE_STAGES)
STAGE_OUTPUTS = {s['key']: s.get('outputs', []) for s in PIPELINE_STAGES}


# Canonical cache filenames — single source of truth for all stages.
# Import via: from lib.manifest import CACHE_FILES
CACHE_FILES = {
    'compiled_rules': 'compiled_rules.json',
    'prepare_summary': 'prepare_summary.json',
    'commits':        '01_commits.json',
    'build_context':  '02_build_context.json',
    'kbuild_map':     '02_kbuild_static_map.json',
    'product_map':    '03_product_map.json',
    'filtered':       '04_filtered_commits.json',
    'scored':         '05_scored_commits.json',
    'relevant':       '06_relevant_commits.json',
}


def load_manifest(path=None):
    """Return the MANIFEST dict.

    If *path* is given, load from that path instead of the package default.
    Exists for callers that import the function explicitly.
    """
    if path is None:
        return dict(MANIFEST)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
