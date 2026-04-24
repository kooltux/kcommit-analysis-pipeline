"""Input validation for kcommit-analysis-pipeline.

v8.0 changes vs v7.19:
  - Dropped from __future__ import print_function (Py2 dead code).
  - %-formatting replaced with f-strings.
  - Git-ref validation: rev_old / rev_new verified against source_dir via
    `git rev-parse --verify` when source_dir exists.
  - Scoring multiplier validation: cfg['scoring'] values must be non-negative numbers.
  - Profile weight validation: profiles.active weights must be integers 0–100.
  - collect.score_workers validation: must be a non-negative integer (0 = auto).
"""
import os
import subprocess


def validate_inputs(cfg):
    """Validate mandatory and optional inputs.

    Returns:
        (problems, notices)
        problems – list of blocking error strings (stage should abort)
        notices  – list of informational strings (stage prints but continues)
    """
    problems = []
    notices  = []

    kernel = cfg.get('kernel', {}) or {}
    inputs = cfg.get('inputs', {}) or {}

    # ── Mandatory: kernel source directory ───────────────────────────────────
    source_dir = kernel.get('source_dir')
    if not source_dir:
        problems.append('kernel.source_dir is not configured')
    elif not os.path.isdir(source_dir):
        problems.append(f'kernel.source_dir does not exist: {source_dir}')

    # ── Mandatory: revision range ─────────────────────────────────────────────
    rev_old = kernel.get('rev_old')
    rev_new = kernel.get('rev_new')
    if not rev_old:
        problems.append('kernel.rev_old is not configured')
    if not rev_new:
        problems.append('kernel.rev_new is not configured')

    # ── Git ref validation (only when source_dir is available) ───────────────
    if source_dir and os.path.isdir(source_dir):
        for ref_key, ref_val in (('rev_old', rev_old), ('rev_new', rev_new)):
            if ref_val:
                rc = subprocess.call(
                    ['git', '-C', source_dir, 'rev-parse', '--verify', ref_val],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if rc != 0:
                    problems.append(
                        f'kernel.{ref_key}={ref_val!r} is not a valid git ref in {source_dir}')

    # ── Optional: kernel config file ─────────────────────────────────────────
    kconfig = inputs.get('kernel_config')
    if not kconfig:
        notices.append('notice: inputs.kernel_config not set – '
                       'Kconfig symbol mapping will be skipped')
    elif not os.path.isfile(kconfig):
        notices.append(f'notice: inputs.kernel_config not found ({kconfig}) – '
                       'Kconfig symbol mapping will be skipped')

    # ── Optional: build directory ─────────────────────────────────────────────
    build_dir = inputs.get('build_dir')
    if build_dir and not os.path.isdir(build_dir):
        notices.append(f'notice: inputs.build_dir not found ({build_dir}) – '
                       'artifact scanning will be skipped')

    # ── Scoring multiplier validation ─────────────────────────────────────────
    for key, val in (cfg.get('scoring') or {}).items():
        if not isinstance(val, (int, float)) or val < 0:
            problems.append(
                f'scoring.{key} must be a non-negative number, got {val!r}')

    # ── Profile weight validation ─────────────────────────────────────────────
    active = (cfg.get('profiles', {}) or {}).get('active') or {}
    if isinstance(active, dict):
        for name, w in active.items():
            if not isinstance(w, (int, float)) or not (0 <= w <= 100):
                problems.append(
                    f'profiles.active.{name}: weight {w!r} must be 0–100')

    # ── collect.score_workers sanity ──────────────────────────────────────────
    workers = (cfg.get('collect', {}) or {}).get('score_workers')
    if workers is not None:
        try:
            w = int(workers)
            if w < 0:
                problems.append(
                    f'collect.score_workers must be >= 0 (0 = auto), got {workers!r}')
        except (TypeError, ValueError):
            problems.append(
                f'collect.score_workers must be an integer, got {workers!r}')

    return problems, notices
