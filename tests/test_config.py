"""Tests for lib.config — load_config, apply_override, deep_merge."""
import os, json, tempfile

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
    paths = cfg['paths']
    # work_dir is taken from config (may be normalised)
    assert paths['work_dir'].startswith(str(tmp_path))
    # derived paths must all be present and non-empty
    assert paths['cache_dir']
    assert paths['output_dir']
    assert paths['scoring_dir']
    assert paths['templates_dir']
    assert isinstance(paths['profiles_dirs'], list)
    assert isinstance(paths['rules_dirs'], list)


def test_load_config_scoring_dir_override(tmp_path):
    custom_scoring = str(tmp_path / 'my_scoring')
    minimal = {
        'paths':   {'work_dir': str(tmp_path)},
        'kernel':  {'source_dir': '/linux', 'rev_old': 'v6.8', 'rev_new': 'HEAD'},
        'scoring': {'scoring_dir': custom_scoring},
    }
    p = tmp_path / 'cfg.json'
    p.write_text(json.dumps(minimal))
    cfg = load_config(str(p))
    assert cfg['paths']['scoring_dir'] == custom_scoring


def test_load_config_templates_dir_override(tmp_path):
    custom_tpl = str(tmp_path / 'my_html')
    minimal = {
        'paths':   {'work_dir': str(tmp_path)},
        'kernel':  {'source_dir': '/linux', 'rev_old': 'v6.8', 'rev_new': 'HEAD'},
        'reports': {'templates_dir': custom_tpl},
    }
    p = tmp_path / 'cfg.json'
    p.write_text(json.dumps(minimal))
    cfg = load_config(str(p))
    assert cfg['paths']['templates_dir'] == custom_tpl


def test_apply_override_filter_min_score():
    """filter.min_score is the canonical threshold key (E.1c / D.1)."""
    cfg = {'filter': {'min_score': 0}}
    apply_override(cfg, '{"filter": {"min_score": 42}}')
    assert cfg['filter']['min_score'] == 42


# ── ${VAR} / ${CONFIGDIR} expansion ──────────────────────────────────────────
def test_load_config_configdir_expansion(tmp_path):
    """${CONFIGDIR} in scoring.scoring_dir is expanded to the config file directory."""
    minimal = {
        'paths':   {'work_dir': str(tmp_path)},
        'kernel':  {'source_dir': '/linux', 'rev_old': 'v6.8', 'rev_new': 'HEAD'},
        'scoring': {'scoring_dir': '${CONFIGDIR}/myscoring'},
    }
    p = tmp_path / 'cfg.json'
    p.write_text(json.dumps(minimal))
    cfg = load_config(str(p))
    expected = os.path.join(str(tmp_path), 'myscoring')
    assert cfg['paths']['scoring_dir'] == expected


def test_load_config_rules_dirs_normalised(tmp_path):
    """rules.rules_dirs relative paths are normalised to absolute paths."""
    rules_rel = 'my_rules'
    minimal = {
        'paths':   {'work_dir': str(tmp_path)},
        'kernel':  {'source_dir': '/linux', 'rev_old': 'v6.8', 'rev_new': 'HEAD'},
        'rules':   {'rules_dirs': [rules_rel]},
    }
    p = tmp_path / 'cfg.json'
    p.write_text(json.dumps(minimal))
    cfg = load_config(str(p))
    # Each entry in rules_dirs must be absolute
    for d in cfg['paths']['rules_dirs']:
        assert os.path.isabs(d), f"rules_dirs entry not absolute: {d}"


def test_load_config_profiles_dirs_normalised(tmp_path):
    """profiles.profiles_dirs relative paths are normalised to absolute paths."""
    minimal = {
        'paths':    {'work_dir': str(tmp_path)},
        'kernel':   {'source_dir': '/linux', 'rev_old': 'v6.8', 'rev_new': 'HEAD'},
        'profiles': {'profiles_dirs': ['my_profiles'], 'active': {}},
    }
    p = tmp_path / 'cfg.json'
    p.write_text(json.dumps(minimal))
    cfg = load_config(str(p))
    for d in cfg['paths']['profiles_dirs']:
        assert os.path.isabs(d), f"profiles_dirs entry not absolute: {d}"


def test_load_config_rejects_unknown_top_level(tmp_path):
    p = tmp_path / 'cfg.json'
    p.write_text('{"paths":{"work_dir":"w"},"kernel":{"source_dir":"s","rev_old":"a","rev_new":"b"},"bogus":1}')
    import pytest
    with pytest.raises(ValueError):
        load_config(str(p))


