"""Input validation for kcommit-analysis-pipeline."""
import os
import subprocess


# ── filter section ────────────────────────────────────────────────────────────

def _validate_filter(cfg, problems, notices):
    """Validate the optional filter config section."""
    f = cfg.get('filter')
    if f is None:
        return
    if not isinstance(f, dict):
        problems.append('"filter" must be a JSON object')
        return

    known = {'enabled', 'path_blacklist_global', 'require_kconfig_coverage'}
    for k in f:
        if k not in known:
            notices.append(
                f'filter.{k!r} is not a recognised key '
                f'(known: {", ".join(sorted(known))})')

    for bool_key in ('enabled', 'path_blacklist_global'):
        if bool_key in f and not isinstance(f[bool_key], bool):
            problems.append(
                f'filter.{bool_key} must be true or false, got {f[bool_key]!r}')

    rkc = f.get('require_kconfig_coverage', None)
    if rkc is not None and not isinstance(rkc, bool):
        problems.append(
            f'filter.require_kconfig_coverage must be true, false, or null '
            f'(null = auto-detect), got {rkc!r}')


# ── profiles / rules directory validation ─────────────────────────────────────

def _validate_dirs(cfg, problems, notices):
    """Validate profiles_dirs and rules_dirs (single or multiple)."""
    paths = cfg.get('paths', {}) or {}

    # profiles dirs
    pdirs = paths.get('profiles_dirs') or [paths.get('profiles_dir', '')]
    for d in pdirs:
        if d and not os.path.isdir(d):
            problems.append(f'profiles directory not found: {d}')

    # rules dirs
    rdirs = paths.get('rules_dirs') or [paths.get('rules_dir', '')]
    for d in rdirs:
        if d and not os.path.isdir(d):
            problems.append(f'rules directory not found: {d}')

    # active profiles: check they exist in at least one profiles dir
    active_cfg = (cfg.get('profiles', {}) or {}).get('active') or cfg.get('active_profiles') or []
    if isinstance(active_cfg, dict):
        active_names = list(active_cfg.keys())
    else:
        active_names = list(active_cfg)

    if not active_names:
        problems.append('no active profiles configured (profiles.active is empty)')

    valid_pdirs = [d for d in pdirs if d and os.path.isdir(d)]
    for name in active_names:
        found = any(os.path.exists(os.path.join(d, name + '.json')) for d in valid_pdirs)
        if not found and valid_pdirs:
            searched = ', '.join(valid_pdirs)
            problems.append(f'profile {name!r} not found in any profiles directory ({searched})')


# ── shared validation core ────────────────────────────────────────────────────

def _validate_common(cfg, problems, notices):
    """Checks shared by both validate_inputs() and validate_config_only()."""
    kernel = cfg.get('kernel', {}) or {}

    source_dir = kernel.get('source_dir')
    if not source_dir:
        problems.append('kernel.source_dir is not configured')
    elif not os.path.isdir(source_dir):
        problems.append(f'kernel.source_dir does not exist: {source_dir}')

    rev_old = kernel.get('rev_old')
    rev_new = kernel.get('rev_new')
    if not rev_old:
        problems.append('kernel.rev_old is not configured')
    if not rev_new:
        problems.append('kernel.rev_new is not configured')

    kconfig = kernel.get('kernel_config')
    if not kconfig:
        notices.append('notice: inputs.kernel_config not set – '
                       'Kconfig symbol mapping will be skipped')
    elif not os.path.isfile(kconfig):
        notices.append(f'notice: kernel.kernel_config not found ({kconfig}) – '
                       'Kconfig symbol mapping will be skipped')

    build_dir = kernel.get('build_dir')
    if build_dir and not os.path.isdir(build_dir):
        notices.append(f'notice: inputs.build_dir not found ({build_dir}) – '
                       'artifact scanning will be skipped')

    for key, val in (cfg.get('scoring') or {}).items():
        if not isinstance(val, (int, float)) or val < 0:
            problems.append(
                f'scoring.{key} must be a non-negative number, got {val!r}')

    active = (cfg.get('profiles', {}) or {}).get('active') or {}
    if isinstance(active, dict):
        for name, w in active.items():
            if not isinstance(w, (int, float)) or not (0 <= w <= 100):
                problems.append(
                    f'profiles.active.{name}: weight {w!r} must be 0–100')

    workers = (cfg.get('collect', {}) or {}).get('score_workers')
    if workers is not None:
        try:
            if int(workers) < 0:
                problems.append(
                    f'collect.score_workers must be >= 0 (0 = auto), got {workers!r}')
        except (TypeError, ValueError):
            problems.append(
                f'collect.score_workers must be an integer, got {workers!r}')

    min_score = (cfg.get('reports', {}) or {}).get('min_score')
    if min_score is not None:
        try:
            if float(min_score) < 0:
                problems.append(
                    f'reports.min_score must be >= 0, got {min_score!r}')
        except (TypeError, ValueError):
            problems.append(
                f'reports.min_score must be a number, got {min_score!r}')

    for _flag in ('csv_output', 'html_summary', 'xls_output', 'ods_output'):
        _val = (cfg.get('templates', {}) or {}).get(_flag)
        if _val is not None and not isinstance(_val, bool):
            problems.append(
                f'templates.{_flag} must be true or false, got {_val!r}')

    _validate_filter(cfg, problems, notices)
    _validate_dirs(cfg, problems, notices)


# ── public API ────────────────────────────────────────────────────────────────

def validate_inputs(cfg):
    """Validate mandatory and optional inputs, including git-ref verification.

    Returns (problems, notices).
    problems — blocking errors (stage should abort).
    notices  — informational strings (stage prints but continues).
    """
    problems = []
    notices  = []

    _validate_common(cfg, problems, notices)

    kernel     = cfg.get('kernel', {}) or {}
    source_dir = kernel.get('source_dir')
    rev_old    = kernel.get('rev_old')
    rev_new    = kernel.get('rev_new')

    if source_dir and os.path.isdir(source_dir):
        for ref_key, ref_val in (('rev_old', rev_old), ('rev_new', rev_new)):
            if ref_val:
                rc = subprocess.run(
                    ['git', '-C', source_dir, 'rev-parse', '--verify', ref_val],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                if rc != 0:
                    problems.append(
                        f'kernel.{ref_key}={ref_val!r} is not a valid git ref'
                        f' in {source_dir}')

    return problems, notices


def validate_config_only(cfg):
    """Lightweight validation: config structure, paths, and value ranges only.

    Does NOT run git subprocess calls. Safe to call from every stage script.
    Use validate_inputs() (git-ref verification) only in stage 00 and dry-run.
    """
    problems = []
    notices  = []

    _validate_common(cfg, problems, notices)

    hm      = cfg.get('history_mapping') or {}
    hm_mode = hm.get('mode', 'range')
    if hm_mode not in ('range', 'sampled', 'full', 'disabled'):
        problems.append(
            f'history_mapping.mode must be one of range/sampled/full/disabled,'
            f' got {hm_mode!r}')
    hm_step = hm.get('sample_step', 1000)
    if not isinstance(hm_step, int) or hm_step < 1:
        problems.append(
            f'history_mapping.sample_step must be a positive integer, got {hm_step!r}')

    return problems, notices
