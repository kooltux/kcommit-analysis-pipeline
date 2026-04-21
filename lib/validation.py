# Validate mandatory and optional pipeline inputs before stage execution.
from __future__ import print_function
import os


def validate_inputs(cfg):
    problems = []
    notices = []
    kernel = cfg.get('kernel', {})
    inputs = cfg.get('inputs', {})

    source_dir = kernel.get('source_dir')
    kernel_config = inputs.get('kernel_config')
    build_dir = inputs.get('build_dir')

    if not source_dir:
        problems.append('kernel.source_dir is required')
    elif not os.path.isdir(source_dir):
        problems.append('kernel.source_dir does not exist: %s' % source_dir)

    if not kernel_config:
        problems.append('inputs.kernel_config is required')
    elif not os.path.isfile(kernel_config):
        problems.append('inputs.kernel_config does not exist: %s' % kernel_config)

    if build_dir:
        if os.path.isdir(build_dir):
            notices.append('optional build_dir detected: %s' % build_dir)
        else:
            notices.append('optional build_dir not found, continuing without it: %s' % build_dir)
    else:
        notices.append('optional build_dir not configured, continuing without it')

    return problems, notices
