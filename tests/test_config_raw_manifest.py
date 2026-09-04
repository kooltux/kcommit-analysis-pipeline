"""Tests for manifest config generation with partial variable expansion."""

import json
import os
import tempfile
import warnings
from pathlib import Path

import pytest

from lib.config import (
    load_config, 
    load_config_with_raw, 
    _build_raw_merged_config,
    _build_partial_expanded_config,
    _ENV_VARS,
)


def _write_json(parent: Path, name: str, data: dict, comments: str = "") -> Path:
    path = parent / name
    path.write_text(comments + json.dumps(data), encoding="utf-8")
    return path


def test_load_config_with_raw_returns_both_versions(tmp_path: Path):
    """Verify that load_config_with_raw returns expanded and manifest configs."""
    root = _write_json(
        tmp_path, "root.json",
        {
            "vars": {"OUT": "${CONFIGDIR}/out", "WORK": "${OUT}/work"},
            "paths": {"work_dir": "${WORK}", "cache_dir": "${WORK}/cache"},
            "kernel": {"source_dir": "/linux", "rev_old": "v6.8", "rev_new": "HEAD"},
        }
    )
    
    expanded, manifest = load_config_with_raw(str(root))
    
    # Expanded should have fully resolved paths
    assert "work_dir" in expanded["paths"]
    assert expanded["paths"]["work_dir"].startswith(str(tmp_path.resolve()))
    
    # Manifest should preserve intermediate variable references in paths
    # (paths with ${} refs are not resolved by _resolve_known_paths)
    assert "paths" in manifest
    assert manifest["paths"]["work_dir"] == "${WORK}"
    assert manifest["paths"]["cache_dir"] == "${WORK}/cache"
    
    # Vars section: CONFIGDIR is expanded, but intermediate vars keep refs
    assert str(tmp_path.resolve()) in manifest["vars"]["OUT"]
    assert "${OUT}" in manifest["vars"]["WORK"]


def test_manifest_config_expands_env_vars_only(tmp_path: Path):
    """Verify that manifest config expands env vars but keeps intermediate vars."""
    sub = tmp_path / "sub"
    sub.mkdir()
    
    # Base fragment with variables
    _write_json(
        sub, "base.json",
        {
            "vars": {"OUT": "${CONFIGDIR}/out", "CACHE": "${OUT}/cache"},
            "paths": {"work_dir": "${OUT}", "cache_dir": "${CACHE}"},
        }
    )
    
    # Root config that includes the fragment
    root = _write_json(tmp_path, "root.json", {"include": ["sub/base.json"]})
    
    expanded, manifest = load_config_with_raw(str(root))
    
    # Expanded should have fully resolved absolute paths
    assert expanded["paths"]["work_dir"].startswith(str(tmp_path.resolve()))
    
    # Manifest paths keep intermediate refs (not resolved)
    assert manifest["paths"]["work_dir"] == "${OUT}"
    assert manifest["paths"]["cache_dir"] == "${CACHE}"
    
    # Vars: CONFIGDIR expanded, intermediate refs preserved
    assert str(tmp_path.resolve()) in manifest["vars"]["OUT"]
    assert "${OUT}" in manifest["vars"]["CACHE"]


def test_build_partial_expanded_config(tmp_path: Path):
    """Test _build_partial_expanded_config function."""
    root = _write_json(
        tmp_path, "root.json",
        {
            "vars": {"MY_VAR": "${CONFIGDIR}/my_value", "DERIVED": "${MY_VAR}/subpath"},
            "kernel": {"source_dir": "${MY_VAR}/linux", "rev_old": "v6.8", "rev_new": "HEAD"},
        }
    )
    
    partial = _build_partial_expanded_config(str(root))
    
    # CONFIGDIR should be expanded
    assert str(tmp_path.resolve()) in partial["vars"]["MY_VAR"]
    # But ${MY_VAR} should remain in DERIVED
    assert "${MY_VAR}" in partial["vars"]["DERIVED"]
    
    # kernel.source_dir should have ${MY_VAR} unexpanded
    assert "${MY_VAR}" in partial["kernel"]["source_dir"]
    
    # Should NOT have _meta or config_dir
    assert "_meta" not in partial
    assert "config_dir" not in partial


def test_manifest_would_contain_mixed_references(tmp_path: Path):
    """
    Simulate what would be written to pipeline_config.json.
    This test documents the expected behavior for the manifest.
    """
    root = _write_json(
        tmp_path, "root.json",
        {
            "vars": {"MY_OUT": "${CONFIGDIR}/output", "MY_CACHE": "${MY_OUT}/cache"},
            "paths": {"work_dir": "${MY_OUT}", "cache_dir": "${MY_CACHE}"},
            "kernel": {"source_dir": "/linux", "rev_old": "v6.8", "rev_new": "HEAD"},
        }
    )
    
    _, manifest = load_config_with_raw(str(root))
    
    # Simulate the filtering done in _dump_merged_config
    dump_cfg = {k: v for k, v in manifest.items() if k not in ('_meta', 'config_dir')}
    
    # CONFIGDIR is expanded in MY_OUT
    assert str(tmp_path.resolve()) in dump_cfg["vars"]["MY_OUT"]
    
    # MY_CACHE keeps ${MY_OUT} reference
    assert "${MY_OUT}" in dump_cfg["vars"]["MY_CACHE"]
    
    # paths keep intermediate refs
    assert dump_cfg["paths"]["work_dir"] == "${MY_OUT}"
    assert dump_cfg["paths"]["cache_dir"] == "${MY_CACHE}"
    
    # Verify that _meta and config_dir are filtered out
    assert "_meta" not in dump_cfg
    assert "config_dir" not in dump_cfg


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_manifest_config_with_array_merges(tmp_path: Path):
    """Verify that array merges work correctly in manifest config."""
    _write_json(tmp_path, "base.json", {"tags": ["base", "common"]})
    _write_json(tmp_path, "frag.json", {"tags": ["frag", "common"]})
    root = _write_json(tmp_path, "root.json", {"include": ["base.json", "frag.json"]})
    
    _, manifest = load_config_with_raw(str(root))
    
    # Arrays should be merged with deduplication
    assert manifest["tags"] == ["base", "common", "frag"]


def test_env_vars_constant(tmp_path: Path):
    """Verify that _ENV_VARS contains the expected environment variables."""
    assert "WORKSPACE" in _ENV_VARS
    assert "TOOLDIR" in _ENV_VARS
    assert "CONFIGDIR" in _ENV_VARS
    assert "CWD" in _ENV_VARS
