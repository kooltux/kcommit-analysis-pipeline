"""Tests for lib.validation — validate_config_only, _validate_filter, _schema_problems."""
import os

from lib.validation import validate_config_only, validate_inputs


def _base(tmp_path):
    return {
        'paths':   {'work_dir': str(tmp_path)},
        'kernel':  {'source_dir': str(tmp_path), 'rev_old': 'v6.8', 'rev_new': 'HEAD'},
        'profiles': {'active': {'security_fixes': 100}},
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
    cfg['profiles']['active'] = {'security_fixes': 150}
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
    """filter.min_score must be float — passing a string triggers a schema error."""
    cfg = _base(tmp_path)
    cfg['filter'] = {'min_score': 'high'}   # 'high' is not a float/int
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


# ── collect section (I-series: new schema keys) ───────────────────────────────
def test_collect_unknown_key_is_not_a_problem(tmp_path):
    """Unrecognised collect keys are tolerated (schema validates known keys only)."""
    cfg = _base(tmp_path)
    cfg['collect'] = {'no_merges': True, 'max_commits': 100}
    problems, _ = validate_config_only(cfg)
    assert not any('collect' in p for p in problems)


def test_collect_wrong_type_for_max_commits(tmp_path):
    """collect.max_commits must be int — a string triggers a schema type error."""
    cfg = _base(tmp_path)
    cfg['collect'] = {'max_commits': 'all'}
    problems, _ = validate_config_only(cfg)
    assert any('max_commits' in p for p in problems)


def test_collect_wrong_type_for_score_workers(tmp_path):
    """collect.score_workers must be int."""
    cfg = _base(tmp_path)
    cfg['collect'] = {'score_workers': 'auto'}
    problems, _ = validate_config_only(cfg)
    assert any('score_workers' in p for p in problems)


# ── history_mapping section (I-series: new schema keys) ──────────────────────
def test_history_mapping_max_failure_rate_wrong_type(tmp_path):
    """history_mapping.max_failure_rate must be float."""
    cfg = _base(tmp_path)
    cfg['history_mapping'] = {'max_failure_rate': 'high'}
    problems, _ = validate_config_only(cfg)
    assert any('max_failure_rate' in p for p in problems)


def test_history_mapping_max_commits_per_probe_wrong_type(tmp_path):
    """history_mapping.max_commits_per_probe must be int."""
    cfg = _base(tmp_path)
    cfg['history_mapping'] = {'max_commits_per_probe': 'lots'}
    problems, _ = validate_config_only(cfg)
    assert any('max_commits_per_probe' in p for p in problems)


def test_history_mapping_valid_full_config(tmp_path):
    """A fully-specified history_mapping block raises no problems."""
    cfg = _base(tmp_path)
    cfg['history_mapping'] = {
        'mode': 'sampled',
        'sample_step': 250,
        'max_commits_per_probe': 5,
        'max_failure_rate': 0.1,
    }
    problems, _ = validate_config_only(cfg)
    assert not any('history_mapping' in p for p in problems)


# ── reports section (I-series: title/top_n, no min_score) ────────────────────
def test_reports_top_n_wrong_type(tmp_path):
    """reports.top_n must be int."""
    cfg = _base(tmp_path)
    cfg['reports'] = {'top_n': 'all'}
    problems, _ = validate_config_only(cfg)
    assert any('top_n' in p for p in problems)


def test_reports_valid_config(tmp_path):
    """A valid reports block raises no problems."""
    cfg = _base(tmp_path)
    cfg['reports'] = {'title': 'My Report', 'outputs': ['html', 'csv'], 'top_n': 100}
    problems, _ = validate_config_only(cfg)
    assert not any('reports' in p for p in problems)


def test_validate_unknown_nested_key():
    cfg = {
        'paths': {'work_dir': '/tmp'},
        'kernel': {'source_dir': '/src', 'rev_old': 'a', 'rev_new': 'b', 'bogus': 1},
    }
    problems, notices = validate_inputs(cfg)
    assert any('kernel.bogus' in p for p in problems)


def test_validate_loaded_config_allows_derived_fields(tmp_path):
    cfg = {
        'paths': {
            'work_dir': str(tmp_path),
            'cache_dir': str(tmp_path / 'cache'),
            'output_dir': str(tmp_path / 'output'),
            'profiles_dirs': [str(tmp_path / 'profiles')],
            'rules_dirs': [str(tmp_path / 'rules')],
            'scoring_dir': str(tmp_path / 'scoring'),
            'templates_dir': str(tmp_path / 'html'),
        },
        'kernel': {'source_dir': str(tmp_path / 'linux'), 'rev_old': 'a', 'rev_new': 'b'},
        'profiles': {'active': {'p': 100}},
        '_meta': {'config_dir': str(tmp_path)},
        'config_dir': str(tmp_path),
    }
    (tmp_path / 'linux').mkdir()
    (tmp_path / 'profiles').mkdir()
    (tmp_path / 'rules').mkdir()
    (tmp_path / 'profiles' / 'p.json').write_text('{}')
    problems, notices = validate_inputs(cfg)
    assert not any('unknown key' in p or 'unknown top-level section' in p for p in problems)
