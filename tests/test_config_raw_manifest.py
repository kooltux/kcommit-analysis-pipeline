"""Tests for raw (non-expanded) config manifest generation."""

import json
import os
import tempfile
import warnings
from pathlib import Path

import pytest

from lib.config import load_config, load_config_with_raw, _build_raw_merged_config


def _write_json(parent: Path, name: str, data: dict, comments: str = "") -> Path:
    path = parent / name
    path.write_text(comments + json.dumps(data), encoding="utf-8")
    return path


def test_load_config_with_raw_returns_both_versions(tmp_path: Path):
    """Verify that load_config_with_raw returns both expanded and raw configs."""
    root = _write_json(
        tmp_path, "root.json",
        {
            "vars": {"OUT": "${CONFIGDIR}/out", "WORK": "${OUT}/work"},
            "paths": {"work_dir": "${WORK}", "cache_dir": "${WORK}/cache"},
            "kernel": {"source_dir": "/linux", "rev_old": "v6.8", "rev_new": "HEAD"},
        }
    )
    
    expanded, raw = load_config_with_raw(str(root))
    
    # Expanded should have resolved paths
    assert "work_dir" in expanded["paths"]
    assert expanded["paths"]["work_dir"].startswith(str(tmp_path.resolve()))
    
    # Raw should preserve variable references
    assert "paths" in raw
    assert raw["paths"]["work_dir"] == "${WORK}"
    assert raw["paths"]["cache_dir"] == "${WORK}/cache"
    
    # Raw should have vars section as-is
    assert "vars" in raw
    assert raw["vars"]["OUT"] == "${CONFIGDIR}/out"
    assert raw["vars"]["WORK"] == "${OUT}/work"


def test_raw_config_preserves_variables_with_includes(tmp_path: Path):
    """Verify that raw config preserves variables when using includes."""
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
    
    expanded, raw = load_config_with_raw(str(root))
    
    # Expanded should have resolved absolute paths
    assert expanded["paths"]["work_dir"].startswith(str(tmp_path.resolve()))
    
    # Raw should preserve the variable references
    assert raw["paths"]["work_dir"] == "${OUT}"
    assert raw["paths"]["cache_dir"] == "${CACHE}"
    assert raw["vars"]["OUT"] == "${CONFIGDIR}/out"


def test_build_raw_merged_config_standalone(tmp_path: Path):
    """Test _build_raw_merged_config as a standalone function."""
    # Use valid top-level keys that are in the schema
    root = _write_json(
        tmp_path, "root.json",
        {
            "vars": {"MY_VAR": "${CONFIGDIR}/my_value"},
            "kernel": {"source_dir": "${MY_VAR}/linux", "rev_old": "v6.8", "rev_new": "HEAD"},
        }
    )
    
    raw = _build_raw_merged_config(str(root))
    
    # Should have vars section
    assert "vars" in raw
    assert raw["vars"]["MY_VAR"] == "${CONFIGDIR}/my_value"
    
    # Should preserve variable references in other sections
    assert raw["kernel"]["source_dir"] == "${MY_VAR}/linux"
    
    # Should NOT have _meta or config_dir
    assert "_meta" not in raw
    assert "config_dir" not in raw


def test_manifest_would_contain_variable_references(tmp_path: Path):
    """
    Simulate what would be written to pipeline_config.json.
    This test documents the expected behavior for the manifest.
    """
    root = _write_json(
        tmp_path, "root.json",
        {
            "vars": {"WORKSPACE": "/opt/workspace", "OUT": "${WORKSPACE}/output"},
            "paths": {"work_dir": "${OUT}", "cache_dir": "${OUT}/cache"},
            "kernel": {"source_dir": "/linux", "rev_old": "v6.8", "rev_new": "HEAD"},
        }
    )
    
    _, raw = load_config_with_raw(str(root))
    
    # Simulate the filtering done in _dump_merged_config
    dump_cfg = {k: v for k, v in raw.items() if k not in ('_meta', 'config_dir')}
    
    # Verify that variable references are preserved
    assert dump_cfg["vars"]["OUT"] == "${WORKSPACE}/output"
    assert dump_cfg["paths"]["work_dir"] == "${OUT}"
    assert dump_cfg["paths"]["cache_dir"] == "${OUT}/cache"
    
    # Verify that _meta and config_dir are filtered out
    assert "_meta" not in dump_cfg
    assert "config_dir" not in dump_cfg


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_raw_config_with_array_merges(tmp_path: Path):
    """Verify that array merges work correctly in raw config."""
    _write_json(tmp_path, "base.json", {"tags": ["base", "common"]})
    _write_json(tmp_path, "frag.json", {"tags": ["frag", "common"]})
    root = _write_json(tmp_path, "root.json", {"include": ["base.json", "frag.json"]})
    
    _, raw = load_config_with_raw(str(root))
    
    # Arrays should be merged with deduplication
    assert raw["tags"] == ["base", "common", "frag"]
