"""Default TOOLDIR keeps the spelling used to start the tool (v20.1.1)."""
import os
import sys
from pathlib import Path

from lib import config
from lib.config import relativize_paths

REPO = Path(config.__file__).resolve().parents[1]


def _linked_tool(tmp_path):
    root = os.path.realpath(str(tmp_path))
    tools = os.path.join(root, 'project', 'tools')
    os.makedirs(tools)
    link = os.path.join(tools, 'kcap')
    os.symlink(str(REPO), link)
    return root, link


def test_default_tool_dir_follows_the_symlink_used_to_start_the_tool(tmp_path, monkeypatch):
    _, link = _linked_tool(tmp_path)
    monkeypatch.setattr(sys, 'argv', [os.path.join(link, 'kcommit_pipeline.py'), 'run'])
    assert config._default_tool_dir() == link
    monkeypatch.delenv('TOOLDIR', raising=False)
    variables = config._initial_variables(str(tmp_path))
    assert variables['TOOLDIR'] == link


def test_default_tool_dir_falls_back_to_the_physical_location(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', [str(tmp_path / 'other' / 'pytest')])
    physical = os.path.dirname(os.path.dirname(os.path.abspath(config.__file__)))
    assert config._default_tool_dir() == physical
    monkeypatch.setattr(sys, 'argv', [])
    assert config._default_tool_dir() == physical


def test_exported_tool_path_is_short_when_tool_is_a_nearby_symlink(tmp_path):
    root, link = _linked_tool(tmp_path)
    outdir = os.path.join(root, 'project', 'config', 'run', 'output')
    os.makedirs(outdir)
    cfg = {'vars': {'TOOLDIR': link},
           'rules': {'rules_dirs': [link + '/configs/rules']}}
    out = relativize_paths(cfg, outdir)
    assert out['vars']['TOOLDIR'] == '../../../tools/kcap'
    assert out['rules']['rules_dirs'] == ['../../../tools/kcap/configs/rules']
