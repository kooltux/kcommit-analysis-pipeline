"""Every shipped JSON/JSONC config file must parse (v19.11.1).

Regression guard: configs/conf.d/02_profiles.json used to leave a trailing
comma before the closing brace once its comment-only block was stripped, so
the shipped example configuration could not be loaded at all.
"""
from pathlib import Path

import pytest

from lib.config import load_json

CONFIGS = Path(__file__).resolve().parents[1] / 'configs'


def _files(pattern):
    return sorted(CONFIGS.glob(pattern))


def test_shipped_config_dirs_are_not_empty():
    assert _files('conf.d/*.json')
    assert _files('profiles/*.json')
    assert _files('ai/*.json')
    assert (CONFIGS / 'example-arm-embedded-full.json').is_file()


@pytest.mark.parametrize('path', _files('conf.d/*.json'), ids=lambda p: p.name)
def test_conf_d_fragment_parses(path):
    assert isinstance(load_json(str(path)), dict)


@pytest.mark.parametrize('path', _files('profiles/*.json'), ids=lambda p: p.name)
def test_shipped_profile_parses(path):
    data = load_json(str(path))
    assert isinstance(data, dict) and data.get('rules')


@pytest.mark.parametrize('path', _files('ai/*.json'), ids=lambda p: p.name)
def test_shipped_ai_json_parses(path):
    assert isinstance(load_json(str(path)), dict)


def test_example_config_parses_and_includes_all_fragments():
    data = load_json(str(CONFIGS / 'example-arm-embedded-full.json'))
    included = {Path(name).name for name in data['include']}
    assert included == {p.name for p in _files('conf.d/*.json')}
