"""Tests for ordered JSONC configuration includes."""

import json
import warnings
from pathlib import Path

import pytest

from lib.config import load_config


def _write_json(parent: Path, name: str, data: dict, comments: str = "") -> Path:
    path = parent / name
    path.write_text(comments + json.dumps(data), encoding="utf-8")
    return path


def _paths(tmp_path):
    return {"work_dir": str(tmp_path / "work")}


def test_ordered_includes_and_merge_order(tmp_path: Path):
    _write_json(tmp_path, "base.json", {"paths": _paths(tmp_path), "model": {"name": "base"}, "tags": ["base"]})
    _write_json(tmp_path, "frag1.json", {"model": {"name": "frag1"}, "tags": ["frag1"], "extra": {"from": "frag1"}})
    _write_json(tmp_path, "frag2.json", {"model": {"name": "frag2", "version": 2}, "tags": ["frag2"], "extra": {"from": "frag2"}})
    root = _write_json(tmp_path, "root.json", {"include": ["base.json", "frag1.json", "frag2.json"]})

    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        cfg = load_config(str(root))

    assert cfg["model"] == {"name": "frag2", "version": 2}
    assert cfg["extra"]["from"] == "frag2"
    assert cfg["tags"] == ["base", "frag1", "frag2"]
    assert any("Repeated assignment" in str(record.message) for record in records)


def test_array_deduplication_stable(tmp_path: Path):
    _write_json(tmp_path, "base.json", {"paths": _paths(tmp_path), "items": [{"id": 1}, {"id": 2}]})
    _write_json(tmp_path, "frag.json", {"items": [{"id": 2}, {"id": 3}]})
    root = _write_json(tmp_path, "root.json", {"include": ["base.json", "frag.json"]})

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        cfg = load_config(str(root))

    assert cfg["items"] == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert any(event["event"] == "array_contribution" for event in cfg["_meta"]["include_events"])


def test_comments_are_accepted(tmp_path: Path):
    root = _write_json(tmp_path, "root.json", {"paths": _paths(tmp_path)}, "// JSONC comment\n")
    cfg = load_config(str(root))
    assert cfg["paths"]["work_dir"] == str((tmp_path / "work").resolve())


def test_include_configs_rejected(tmp_path: Path):
    root = _write_json(tmp_path, "root.json", {"include_configs": ["other.json"], "paths": _paths(tmp_path)})
    with pytest.raises(ValueError, match="include_configs"):
        load_config(str(root))


def test_cycle_detection(tmp_path: Path):
    a = _write_json(tmp_path, "a.json", {"include": ["b.json"]})
    _write_json(tmp_path, "b.json", {"include": ["a.json"]})
    with pytest.raises(ValueError, match="cyclic include"):
        load_config(str(a))


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_shared_fragment_via_separate_branches_allowed(tmp_path: Path):
    _write_json(tmp_path, "shared.json", {"value": 42})
    _write_json(tmp_path, "left.json", {"include": ["shared.json"], "side": "left"})
    _write_json(tmp_path, "right.json", {"include": ["shared.json"], "side": "right"})
    root = _write_json(tmp_path, "root.json", {"include": ["left.json", "right.json"]})
    cfg = load_config(str(root))
    assert cfg["value"] == 42
    assert cfg["side"] == "right"


def test_fragment_local_vars_and_configdir_resolution(tmp_path: Path):
    """Variables are global and resolved after merging; CONFIGDIR is the root config directory."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _write_json(
        sub,
        "base.json",
        {
            "vars": {"OUT": "${CONFIGDIR}/out", "ASSETS": "${CONFIGDIR}/assets", "CACHE": "${CONFIGDIR}/cache"},
            "paths": {"work_dir": "${OUT}", "assets_dir": "${ASSETS}", "cache_dir": "${CACHE}"},
        },
    )
    root = _write_json(tmp_path, "root.json", {"include": ["sub/base.json"]})
    cfg = load_config(str(root))
    # CONFIGDIR is the directory containing root.json (tmp_path), not the fragment directory
    assert cfg["paths"]["work_dir"] == str((tmp_path / "out").resolve())
    assert cfg["paths"]["assets_dir"] == str((tmp_path / "assets").resolve())
    assert cfg["paths"]["cache_dir"] == str((tmp_path / "cache").resolve())


def test_monolithic_config_still_works(tmp_path: Path):
    root = _write_json(tmp_path, "root.json", {"paths": _paths(tmp_path), "kernel": {"source_dir": "/linux", "rev_old": "v6.8", "rev_new": "HEAD"}})
    cfg = load_config(str(root))
    assert cfg["kernel"]["rev_new"] == "HEAD"
    assert cfg["paths"]["scoring_dir"]
    assert cfg["paths"]["templates_dir"]
    assert cfg["paths"]["assets_dir"]
