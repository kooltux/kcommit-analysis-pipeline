"""Input validation for kcommit-analysis-pipeline.

    produce notices (printed to stdout) not blocking errors.
  - Returns (errors: list[str], notices: list[str]) instead of raising.
  - modules_file / modules_list keys silently accepted but not required.
"""
import os


def validate_inputs(cfg):
    """Validate mandatory and optional inputs.

    Returns:
        (problems, notices)
        problems – list of blocking error strings (stage should abort)
        notices  – list of informational strings (stage should print but continue)
    """
    problems = []
    notices  = []

    kernel = cfg.get('kernel', {}) or {}
    inputs = cfg.get('inputs', {}) or {}

    # Mandatory: kernel source directory
    source_dir = kernel.get('source_dir')
    if not source_dir:
        problems.append('kernel.source_dir is not configured')
    elif not os.path.isdir(source_dir):
        problems.append('kernel.source_dir does not exist: %s' % source_dir)

    # Mandatory: revision range
    if not kernel.get('rev_old'):
        problems.append('kernel.rev_old is not configured')
    if not kernel.get('rev_new'):
        problems.append('kernel.rev_new is not configured')

    # Optional: kernel config file
    kconfig = inputs.get('kernel_config')
    if not kconfig:
        notices.append('notice: inputs.kernel_config not set – '
                       'Kconfig symbol mapping will be skipped')
    elif not os.path.isfile(kconfig):
        notices.append('notice: inputs.kernel_config not found (%s) – '
                       'Kconfig symbol mapping will be skipped' % kconfig)

    # Optional: build directory
    build_dir = inputs.get('build_dir')
    if build_dir and not os.path.isdir(build_dir):
        notices.append('notice: inputs.build_dir not found (%s) – '
                       'artifact scanning will be skipped' % build_dir)

    return problems, notices
