"""Integration test: stage 00 (prepare_pipeline) with the example config.

Runs lib/stages/st00_prepare.run() in a sandbox tmp directory, pointing at
the real configs/profiles/ and configs/rules/ tree that ships with the repo.
Git rev-parse calls are bypassed by patching validate_inputs so the test does
not require a live kernel source tree.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Locate the repo root relative to this test file so the test is portable.
REPO_ROOT   = Path(__file__).parent.parent.resolve()
PROFILES_DIR = REPO_ROOT / 'configs' / 'profiles'
RULES_DIR    = REPO_ROOT / 'configs' / 'rules'


def _make_cfg(tmp_path):
    """Build a minimal config dict that mirrors the example config structure."""
    src = tmp_path / 'linux'
    src.mkdir()
    cache = tmp_path / 'cache'
    cache.mkdir()
    return {
        'paths': {
            'work_dir':      str(tmp_path),
            'cache_dir':     str(cache),
            'profiles_dirs': [str(PROFILES_DIR)],
            'rules_dirs':    [str(RULES_DIR)],
        },
        'kernel': {
            'source_dir': str(src),
            'rev_old':    'v6.8',
            'rev_new':    'HEAD',
        },
        'profiles': {
            'active': {
                'security_fixes':    100,
                'security_features':  90,
                'performance':        70,
            },
        },
    }


@pytest.mark.skipif(
    not PROFILES_DIR.is_dir() or not RULES_DIR.is_dir(),
    reason='configs/profiles or configs/rules not present in repo'
)
def test_st00_run_with_example_config(tmp_path):
    """Stage 00 must compile rules and write both cache files without error."""
    from lib.stages import st00_prepare
    from lib.manifest import CACHE_FILES

    cfg   = _make_cfg(tmp_path)
    cache = cfg['paths']['cache_dir']

    # Bypass git rev-parse — we have no live kernel repo in CI
    with patch('lib.stages.st00_prepare.validate_inputs',
               return_value=([], ['notice: git validation skipped in test'])):
        summary = st00_prepare.run(cfg, cache)

    # ── compiled_rules.json must exist and be valid JSON ──────────────────────
    compiled_path = os.path.join(cache, CACHE_FILES['compiled_rules'])
    assert os.path.isfile(compiled_path), 'compiled_rules.json not written'
    with open(compiled_path) as f:
        compiled = json.load(f)
    assert isinstance(compiled, dict), 'compiled_rules.json is not a dict'

    # ── prepare_summary.json must exist ──────────────────────────────────────
    summary_path = os.path.join(cache, CACHE_FILES['prepare_summary'])
    assert os.path.isfile(summary_path), 'prepare_summary.json not written'
    with open(summary_path) as f:
        on_disk = json.load(f)

    # ── all 3 active profiles must be compiled ───────────────────────────────
    expected_profiles = {'security_fixes', 'security_features', 'performance'}
    assert expected_profiles.issubset(set(compiled.keys())), (
        f"Missing profiles in compiled_rules: "
        f"{expected_profiles - set(compiled.keys())}"
    )

    # ── each profile must have at least one rule compiled ────────────────────
    for pname in expected_profiles:
        rules = compiled[pname].get('rules', {})
        assert rules, f"Profile {pname!r} has no compiled rules"

    # ── summary return value must list the 3 profiles ────────────────────────
    assert set(summary.get('profiles', [])) == expected_profiles
    for pname in expected_profiles:
        assert summary['rule_counts'].get(pname, 0) > 0, (
            f"Profile {pname!r} has rule_count=0 in summary"
        )

    # ── on-disk summary matches in-memory return value ───────────────────────
    assert on_disk['profiles'] == summary['profiles']
    assert on_disk['rule_counts'] == summary['rule_counts']
