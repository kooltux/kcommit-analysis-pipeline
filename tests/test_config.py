"""Tests for lib.config — load_config, apply_override, deep_merge."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from lib.config import apply_override, deep_merge, load_config


def _tmp_cfg(data):
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(data, f)
    f.flush()
    return f.name


def test_deep_merge_simple():
    base   = {'a': 1, 'b': {'c': 2, 'd': 3}}
    patch  = {'b': {'d': 99}, 'e': 5}
    result = deep_merge(base, patch)
    assert result['a']    == 1
    assert result['b']['c'] == 2
    assert result['b']['d'] == 99
    assert result['e']    == 5


def test_deep_merge_non_destructive():
    base  = {'x': {'y': 1}}
    patch = {'x': {'z': 2}}
    result = deep_merge(base, patch)
    assert result['x']['y'] == 1   # original preserved
    assert result['x']['z'] == 2


def test_apply_override_flat():
    cfg = {'filter': {'min_score': 0}}
    apply_override(cfg, '{"filter":{"min_score":30}}')
    assert cfg['filter']['min_score'] == 30


def test_apply_override_new_key():
    cfg = {'a': 1}
    apply_override(cfg, '{"b": 2}')
    assert cfg['b'] == 2


def test_apply_override_bad_json():
    import pytest
    cfg = {'a': 1}
    with pytest.raises(SystemExit):
        apply_override(cfg, 'not-json')


def test_load_config_minimal(tmp_path):
    minimal = {
        'paths':  {'work_dir': str(tmp_path)},
        'kernel': {'source_dir': '/linux', 'rev_old': 'v6.8', 'rev_new': 'HEAD'},
    }
    p = tmp_path / 'cfg.json'
    p.write_text(json.dumps(minimal))
    cfg = load_config(str(p))
    # load_config may normalise work_dir (e.g. append /work); just check it starts correctly
    assert cfg['paths']['work_dir'].startswith(str(tmp_path))
