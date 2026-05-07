"""Tests for lib.validation — validate_config_only, _validate_filter, _schema_problems."""
import os

from lib.validation import validate_config_only, validate_inputs


def _base(tmp_path):
    return {
        'paths':   {'work_dir': str(tmp_path)},
        'kernel':  {'source_dir': str(tmp_path), 'rev_old': 'v6.8', 'rev_new': 'HEAD'},
        'profiles': {'active': {'security': 100}},
    }


# ── kernel section ────────────────────────────────────────────────────────────
def test_missing_source_dir(tmp_path):
    cfg = _base(tmp_path)
    del cfg['kernel']['source_dir']
    problems, _ = validate_config_only(cfg)
    assert any('source_dir' in p for p in problems)


def test_nonexistent_source_dir(tmp_path):
    cfg = _base(tmp_path)
    cfg['kernel']['source_dir'] = '/does/not/exist'
    problems, _ = validate_config_only(cfg)
    assert any('source_dir' in p for p in problems)


def test_missing_rev_old(tmp_path):
    cfg = _base(tmp_path)
    del cfg['kernel']['rev_old']
    problems, _ = validate_config_only(cfg)
    assert any('rev_old' in p for p in problems)


def test_missing_rev_new(tmp_path):
    cfg = _base(tmp_path)
    del cfg['kernel']['rev_new']
    problems, _ = validate_config_only(cfg)
    assert any('rev_new' in p for p in problems)


def test_missing_kernel_config_is_notice_not_problem(tmp_path):
    cfg = _base(tmp_path)
    # kernel_config not set at all
    problems, notices = validate_config_only(cfg)
    assert not any('kernel_config' in p for p in problems)
    assert any('kernel_config' in n for n in notices)


def test_nonexistent_kernel_config_is_notice(tmp_path):
    cfg = _base(tmp_path)
    cfg['kernel']['kernel_config'] = '/does/not/exist/.config'
    problems, notices = validate_config_only(cfg)
    assert not any('kernel_config' in p for p in problems)
    assert any('kernel_config' in n for n in notices)


# ── profiles section ──────────────────────────────────────────────────────────
def test_empty_active_profiles(tmp_path):
    cfg = _base(tmp_path)
    cfg['profiles']['active'] = {}
    problems, _ = validate_config_only(cfg)
    assert any('active' in p for p in problems)


def test_profile_weight_out_of_range(tmp_path):
    cfg = _base(tmp_path)
    cfg['profiles']['active'] = {'security': 150}
    problems, _ = validate_config_only(cfg)
    assert any('150' in p or 'weight' in p for p in problems)


def test_valid_config_no_problems(tmp_path):
    cfg = _base(tmp_path)
    problems, _ = validate_config_only(cfg)
    assert not problems


# ── filter section ────────────────────────────────────────────────────────────
def test_filter_unknown_key_is_notice(tmp_path):
    cfg = _base(tmp_path)
    cfg['filter'] = {'min_score': 10, 'unknown_key_xyz': True}
    _, notices = validate_config_only(cfg)
    assert any('unknown_key_xyz' in n for n in notices)


def test_filter_require_kconfig_coverage_bad_type(tmp_path):
    cfg = _base(tmp_path)
    cfg['filter'] = {'require_kconfig_coverage': 'yes'}
    problems, _ = validate_config_only(cfg)
    assert any('require_kconfig_coverage' in p for p in problems)


def test_filter_require_kconfig_coverage_valid_bool(tmp_path):
    cfg = _base(tmp_path)
    cfg['filter'] = {'require_kconfig_coverage': True}
    problems, _ = validate_config_only(cfg)
    assert not any('require_kconfig_coverage' in p for p in problems)


# ── schema type validation ────────────────────────────────────────────────────
def test_schema_wrong_type_for_min_score(tmp_path):
    """reports.min_score must be float — passing a string triggers a schema error."""
    cfg = _base(tmp_path)
    cfg['reports'] = {'min_score': 'high'}   # 'high' is not a float
    problems, _ = validate_config_only(cfg)
    assert any('min_score' in p for p in problems)


# ── history_mapping section ───────────────────────────────────────────────────
def test_invalid_history_mapping_mode(tmp_path):
    cfg = _base(tmp_path)
    cfg['history_mapping'] = {'mode': 'unknown_mode'}
    problems, _ = validate_config_only(cfg)
    assert any('mode' in p for p in problems)


def test_valid_history_mapping_modes(tmp_path):
    cfg = _base(tmp_path)
    for mode in ('range', 'sampled', 'full', 'disabled'):
        cfg['history_mapping'] = {'mode': mode}
        problems, _ = validate_config_only(cfg)
        assert not any('mode' in p for p in problems), f"mode={mode} raised: {problems}"


# ── validate_inputs does not crash on missing git dir ─────────────────────────
def test_validate_inputs_invalid_git_dir(tmp_path):
    """validate_inputs with a non-git source_dir should report a problem."""
    cfg = _base(tmp_path)
    # tmp_path exists but is not a git repo, so rev-parse will fail
    problems, _ = validate_inputs(cfg)
    assert any('rev_old' in p or 'rev_new' in p or 'git' in p.lower()
               for p in problems)
