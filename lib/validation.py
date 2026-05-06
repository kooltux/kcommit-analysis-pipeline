"""Input validation for kcommit-analysis-pipeline."""
import os
import subprocess
import sys

from lib.config import CONFIG_SCHEMA

# ── Schema-driven type validation ────────────────────────────────────────────
#
# CONFIG_SCHEMA (lib/config) is the single source of truth for which keys
# exist and what type they must carry.  _validate_schema() walks the top-level
# sections and reports any type mismatch as a problem.
#
# Python 3.11+ supports ExceptionGroup for grouping multiple validation errors
# into a structured aggregate.  On earlier versions we fall back to a plain
# list — the public validate_inputs() / validate_config_only() API is identical
# in both cases (returns problems, notices lists).

_PY_TYPE_MAP = {
    'bool':  bool,
    'int':   int,
    'float': (int, float),
    'str':   str,
    'list':  list,
    'dict':  dict,
    'path':  str,
}

# ExceptionGroup is available from Python 3.11.
_HAS_EXCEPTION_GROUP = sys.version_info >= (3, 11)


def _schema_problems(cfg):
    """Return a list of (dotted_key, message) pairs for every schema violation."""
    errors = []
    for section_name, section_schema in CONFIG_SCHEMA.items():
        section = cfg.get(section_name)
        if section is None or section_schema.get('__type__') != 'dict':
            continue
        if not isinstance(section, dict):
            errors.append((section_name,
                           'must be a JSON object, got {!r}'.format(type(section).__name__)))
            continue
        for key, spec in section_schema.items():
            if key == '__type__':
                continue
            val = section.get(key)
            if val is None:
                continue
            expected_type = _PY_TYPE_MAP.get(spec.get('type'))
            if expected_type is None:
                continue
            if spec.get('list'):
                if not isinstance(val, list):
                    errors.append(('{}.{}'.format(section_name, key),
                                   'must be a list, got {!r}'.format(type(val).__name__)))
                    continue
                for i, item in enumerate(val):
                    if not isinstance(item, expected_type):
                        errors.append((
                            '{}{}[{}]'.format(section_name, key, i),
                            'item must be {}, got {!r}'.format(
                                spec['type'], type(item).__name__)))
            else:
                # bool check must come before int (bool is a subclass of int)
                if spec.get('type') == 'bool' and not isinstance(val, bool):
                    errors.append(('{}.{}'.format(section_name, key),
                                   'must be true or false, got {!r}'.format(val)))
                elif spec.get('type') != 'bool' and not isinstance(val, expected_type):
                    errors.append(('{}.{}'.format(section_name, key),
                                   'must be {}, got {!r}'.format(
                                       spec['type'], type(val).__name__)))
    return errors


def _emit_schema_errors(errors, problems):
    """Append schema errors to *problems*.

    On Python 3.11+ we also build an ExceptionGroup so callers that prefer
    structured exception handling can catch it with `except* ValueError`.
    On Python 3.6–3.10 we only populate the problems list (same public API).
    """
    for dotted_key, msg in errors:
        problems.append('{}: {}'.format(dotted_key, msg))

    if _HAS_EXCEPTION_GROUP and errors:
        # Build a structured aggregate for callers on 3.11+.
        # We raise then immediately catch it so it's stored, not propagated —
        # validate_inputs() still returns (problems, notices) in both paths.
        exc_list = [ValueError('{}: {}'.format(k, m)) for k, m in errors]
        # Return the group for callers that want it; do not raise here.
        return ExceptionGroup('config schema violations', exc_list)  # noqa: F821
    return None


# ── filter section ────────────────────────────────────────────────────────────

def _validate_filter(cfg, problems, notices):
    f = cfg.get('filter')
    if f is None:
        return
    if not isinstance(f, dict):
        problems.append('"filter" must be a JSON object')
        return

    known = set(k for k in CONFIG_SCHEMA.get('filter', {}) if k != '__type__')
    for k in f:
        if k not in known:
            notices.append(
                'filter.{!r} is not a recognised key (known: {})'.format(
                    k, ', '.join(sorted(known))))

    rkc = f.get('require_kconfig_coverage', None)
    if rkc is not None and not isinstance(rkc, bool):
        problems.append(
            'filter.require_kconfig_coverage must be true, false, or null '
            '(null = auto-detect), got {!r}'.format(rkc))


# ── profiles / rules directory validation ─────────────────────────────────────

def _validate_dirs(cfg, problems, notices):
    paths = cfg.get('paths', {}) or {}

    for label, key in (('profiles', 'profiles_dirs'), ('rules', 'rules_dirs')):
        dirs = paths.get(key) or []
        for d in dirs:
            if d and not os.path.isdir(d):
                problems.append('{} directory not found: {}'.format(label, d))

    active_cfg = (cfg.get('profiles', {}) or {}).get('active') or {}
    if isinstance(active_cfg, dict):
        active_names = list(active_cfg.keys())
    else:
        active_names = list(active_cfg)

    if not active_names:
        problems.append(
            'profiles.active is empty — at least one profile must be configured')
        return  # no point checking individual names if the list is empty

    valid_pdirs = [d for d in (paths.get('profiles_dirs') or [])
                   if d and os.path.isdir(d)]
    for name in active_names:
        found = any(os.path.exists(os.path.join(d, name + '.json'))
                    for d in valid_pdirs)
        if not found and valid_pdirs:
            problems.append(
                'profile {!r} not found in any profiles directory ({})'.format(
                    name, ', '.join(valid_pdirs)))


# ── shared validation core ────────────────────────────────────────────────────

def _validate_common(cfg, problems, notices):
    """Checks shared by both validate_inputs() and validate_config_only()."""
    # Schema-driven type checks (replaces manual per-key isinstance checks)
    schema_errors = _schema_problems(cfg)
    _emit_schema_errors(schema_errors, problems)

    kernel = cfg.get('kernel', {}) or {}

    source_dir = kernel.get('source_dir')
    if not source_dir:
        problems.append('kernel.source_dir is not configured')
    elif not os.path.isdir(source_dir):
        problems.append('kernel.source_dir does not exist: {}'.format(source_dir))

    if not kernel.get('rev_old'):
        problems.append('kernel.rev_old is not configured')
    if not kernel.get('rev_new'):
        problems.append('kernel.rev_new is not configured')

    kconfig = kernel.get('kernel_config')
    if not kconfig:
        notices.append('notice: kernel.kernel_config not set — '
                       'Kconfig symbol mapping will be skipped')
    elif not os.path.isfile(kconfig):
        notices.append('notice: kernel.kernel_config not found ({}) — '
                       'Kconfig symbol mapping will be skipped'.format(kconfig))

    build_dir = kernel.get('build_dir')
    if build_dir and not os.path.isdir(build_dir):
        notices.append('notice: kernel.build_dir not found ({}) — '
                       'artifact scanning will be skipped'.format(build_dir))

    active = (cfg.get('profiles', {}) or {}).get('active') or {}
    if isinstance(active, dict):
        for name, w in active.items():
            if not isinstance(w, (int, float)) or not (0 <= w <= 100):
                problems.append(
                    'profiles.active.{}: weight {!r} must be 0–100'.format(name, w))

    _validate_filter(cfg, problems, notices)
    _validate_dirs(cfg, problems, notices)


# ── public API ────────────────────────────────────────────────────────────────

def validate_inputs(cfg):
    """Validate config, inputs, and git refs.

    Returns (problems, notices).
    problems — blocking errors; stage should abort.
    notices  — informational; stage prints but continues.
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
                        'kernel.{}={!r} is not a valid git ref in {}'.format(
                            ref_key, ref_val, source_dir))

    return problems, notices


def validate_config_only(cfg):
    """Lightweight validation: config structure and value ranges only.

    Does NOT run git subprocess calls. Safe to call from every stage script.
    Use validate_inputs() only in stage 00 and dry-run.
    """
    problems = []
    notices  = []

    _validate_common(cfg, problems, notices)

    hm      = cfg.get('history_mapping') or {}
    hm_mode = hm.get('mode', 'range')
    if hm_mode not in ('range', 'sampled', 'full', 'disabled'):
        problems.append(
            'history_mapping.mode must be one of range/sampled/full/disabled,'
            ' got {!r}'.format(hm_mode))
    hm_step = hm.get('sample_step', 1000)
    if not isinstance(hm_step, int) or hm_step < 1:
        problems.append(
            'history_mapping.sample_step must be a positive integer, '
            'got {!r}'.format(hm_step))

    return problems, notices
