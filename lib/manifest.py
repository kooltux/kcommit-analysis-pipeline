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
    'commits':        'commits.json',
    'build_context':  'build_context.json',
    'kbuild_map':     'kbuild_map.json',
    'product_map':    'product_map.json',
    'prefilter_kept': 'prefilter_kept_commits.json',
    'filtered':       'filtered_commits.json',
    'scored':         'scored_commits.json',
    'relevant':       'relevant_commits.json',
    'postfilter_dropped': 'postfilter_dropped_commits.json',
}


# ── Column definitions — single source of truth ───────────────────────────────
# Import via: from lib.manifest import COMMIT_COLS, COMMIT_COLS_FILTERED, ...
COMMIT_COLS          = ["Rank", "SHA", "Subject", "Author", "Date",
                        "Score", "Profiles", "Product Evidence"]
COMMIT_COLS_FILTERED = COMMIT_COLS + ["Filter Reason"]
SUMMARY_COLS         = ["Profile", "Count", "Total Score", "Avg Score"]
MATRIX_COLS          = ["Rank", "SHA", "Subject", "Profile",
                        "Total Score", "Profile Score"]
STATS_COLS           = ["Metric", "Value"]


def load_manifest(path=None):
    """Return the MANIFEST dict.

    If *path* is given, load from that path instead of the package default.
    Exists for callers that import the function explicitly.
    """
    if path is None:
        return dict(MANIFEST)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
