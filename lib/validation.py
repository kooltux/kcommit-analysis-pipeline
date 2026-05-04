"""Input validation for kcommit-analysis-pipeline.

v9.1 changes vs v9.0:
  - _validate_filter(): require_kconfig_coverage now accepts null (None) as
    the documented "auto" state (null=auto, true=force, false=disable).
    Previously the strict bool check incorrectly rejected null and raised
    "filter.require_kconfig_coverage must be true or false, got None".
  - _validate_filter(): require_product_map removed (deprecated since v8.11,
    now a hard unknown-key notice like any other unrecognised key).
  - _validate_common(): new internal helper that holds the ~60 lines of checks
    shared between validate_inputs() and validate_config_only(), eliminating
    the previous copy-paste duplication.
  - lib/stagerunner.py: runstage() unused `index` parameter removed.

v9.0 changes vs v8.11:
  - load_manifest / VERSION / NSTAGES / TEMPLATE_DIR / PIPELINE_STAGES
    re-exported from lib/__init__.py.
  - lib/patterns.py extracted (match, compilepat, precompile_rules).
  - lib/stagerunner.py added (common stage bootstrap).
  - lib/config.py: deep_merge / apply_override added.

v8.4 changes vs v8.3:
  - validate_inputs(): added history_mapping.mode and sample_step validation.

v8.1 changes vs v8.0:
  - validate_config_only() added: lightweight checks without git subprocess
    calls.  Stage scripts 01-06 call this instead of validate_inputs() to
    avoid 14 redundant git subprocesses per full pipeline run.

v8.0 changes vs v7.19:
  - Dropped from __future__ import print_function (Py2 dead code).
  - subprocess.call replaced with subprocess.run.
  - %-formatting replaced with f-strings.
  - Git-ref validation via `git rev-parse --verify`.
  - Scoring multiplier, profile weight, collect.score_workers validation.
"""
import os
import subprocess


# ── filter section ────────────────────────────────────────────────────────────

def _validate_filter(cfg, problems, notices):
    """Validate the optional filter config section (v9.1)."""
    f = cfg.get('filter')
    if f is None:
        return  # section absent — all defaults apply
    if not isinstance(f, dict):
        problems.append('"filter" must be a JSON object')
        return

    # require_product_map removed in v9.1; it will now fall through to the
    # unknown-key notice below like any other unrecognised key.
    known = {'enabled', 'path_blacklist_global', 'require_kconfig_coverage'}
    for k in f:
        if k not in known:
            notices.append(
                f'filter.{k!r} is not a recognised key '
                f'(known: {", ".join(sorted(known))})')

    # enabled / path_blacklist_global: strict bool
    for bool_key in ('enabled', 'path_blacklist_global'):
        if bool_key in f and not isinstance(f[bool_key], bool):
            problems.append(
                f'filter.{bool_key} must be true or false, '
                f'got {f[bool_key]!r}')

    # require_kconfig_coverage: bool OR null
    #   null  → auto: apply coverage check only when kernel_config is present
    #   true  → force: always require coverage; abort if kconfig unavailable
    #   false → disable: skip coverage check entirely
    rkc = f.get('require_kconfig_coverage', None)
    if rkc is not None and not isinstance(rkc, bool):
        problems.append(
            f'filter.require_kconfig_coverage must be true, false, or null '
            f'(null = auto-detect), got {rkc!r}')


# ── shared validation core ────────────────────────────────────────────────────

def _validate_common(cfg, problems, notices):
    """Checks shared by both validate_inputs() and validate_config_only()."""

    kernel = cfg.get('kernel', {}) or {}

    # Mandatory: kernel source directory
    source_dir = kernel.get('source_dir')
    if not source_dir:
        problems.append('kernel.source_dir is not configured')
    elif not os.path.isdir(source_dir):
        problems.append(f'kernel.source_dir does not exist: {source_dir}')

    # Mandatory: revision range
    if not kernel.get('rev_old'):
        problems.append('kernel.rev_old is not configured')
    if not kernel.get('rev_new'):
        problems.append('kernel.rev_new is not configured')

    # Optional: kernel config file
    kconfig = kernel.get('kernel_config')
    if not kconfig:
        notices.append('notice: inputs.kernel_config not set – '
                       'Kconfig symbol mapping will be skipped')
    elif not os.path.isfile(kconfig):
        notices.append(f'notice: kernel.kernel_config not found ({kconfig}) – '
                       'Kconfig symbol mapping will be skipped')

    # Optional: build directory
    build_dir = kernel.get('build_dir')
    if build_dir and not os.path.isdir(build_dir):
        notices.append(f'notice: inputs.build_dir not found ({build_dir}) – '
                       'artifact scanning will be skipped')

    # Scoring multiplier validation
    for key, val in (cfg.get('scoring') or {}).items():
        if not isinstance(val, (int, float)) or val < 0:
            problems.append(
                f'scoring.{key} must be a non-negative number, got {val!r}')

    # Profile weight validation
    active = (cfg.get('profiles', {}) or {}).get('active') or {}
    if isinstance(active, dict):
        for name, w in active.items():
            if not isinstance(w, (int, float)) or not (0 <= w <= 100):
                problems.append(
                    f'profiles.active.{name}: weight {w!r} must be 0–100')

    # collect.score_workers sanity
    workers = (cfg.get('collect', {}) or {}).get('score_workers')
    if workers is not None:
        try:
            if int(workers) < 0:
                problems.append(
                    f'collect.score_workers must be >= 0 (0 = auto), got {workers!r}')
        except (TypeError, ValueError):
            problems.append(
                f'collect.score_workers must be an integer, got {workers!r}')

    # reports.min_score
    min_score = (cfg.get('reports', {}) or {}).get('min_score')
    if min_score is not None:
        try:
            if float(min_score) < 0:
                problems.append(
                    f'reports.min_score must be >= 0, got {min_score!r}')
        except (TypeError, ValueError):
            problems.append(
                f'reports.min_score must be a number, got {min_score!r}')

    # templates output format flags
    for _flag in ('csv_output', 'html_summary', 'xls_output', 'ods_output'):
        _val = (cfg.get('templates', {}) or {}).get(_flag)
        if _val is not None and not isinstance(_val, bool):
            problems.append(
                f'templates.{_flag} must be true or false, got {_val!r}')

    _validate_filter(cfg, problems, notices)


# ── public API ────────────────────────────────────────────────────────────────

def validate_inputs(cfg):
    """Validate mandatory and optional inputs, including git-ref verification.

    Returns:
        (problems, notices)
        problems – list of blocking error strings (stage should abort)
        notices  – list of informational strings (stage prints but continues)
    """
    problems = []
    notices  = []

    _validate_common(cfg, problems, notices)

    # Git ref validation (only when source_dir is present and reachable)
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

    Does NOT run git subprocess calls.  Safe to call from every stage script
    without incurring subprocess overhead per invocation.  Use validate_inputs()
    (which includes git-ref verification) only in stage 00 and dry-run.
    """
    problems = []
    notices  = []

    _validate_common(cfg, problems, notices)

    # history_mapping validation (config-only check, no git needed)
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
