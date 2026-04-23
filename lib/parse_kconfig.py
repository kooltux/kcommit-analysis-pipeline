"""Kernel .config and Kbuild/Makefile parsing helpers.

v7.18 changes vs v7.17:
  - scan_kbuild_tree(root_dir): new function that walks the source tree ONCE
    and returns both (config_to_paths dict, kbuild_files list) in one pass.
    Previously scan_makefile_config_map() and scan_kbuild_makefiles() each
    performed a full independent os.walk of the kernel source tree (75k files,
    ~5k dirs).  Both are now thin wrappers around scan_kbuild_tree() so stage
    02 callers that need both results only pay the traversal cost once.
  - Python 3.6 compatible.
"""
from __future__ import print_function
import io
import os
import re


CONFIG_RE       = re.compile(r'^(CONFIG_[A-Za-z0-9_]+)=(y|m|.+)$')
CONFIG_NOTSET_RE = re.compile(r'^# (CONFIG_[A-Za-z0-9_]+) is not set$')
OBJ_LINE_RE     = re.compile(r'^(obj-[^\s:+?=]+)\s*[:+]?=\s*(.+)$')


def parse_kernel_config(path):
    enabled  = {}
    disabled = set()
    if not path or not os.path.exists(path):
        return {'enabled': enabled, 'disabled': list(disabled)}
    with io.open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            m = CONFIG_RE.match(line)
            if m:
                enabled[m.group(1)] = m.group(2)
                continue
            m = CONFIG_NOTSET_RE.match(line)
            if m:
                disabled.add(m.group(1))
    return {'enabled': enabled, 'disabled': sorted(disabled)}


def scan_kbuild_tree(root_dir):
    """Single-pass walk: return (config_to_paths, kbuild_files).

    config_to_paths: dict mapping CONFIG_XXX -> sorted list of source paths
                     derived from obj-$(CONFIG_XXX) = foo.o Makefile lines.
    kbuild_files:    sorted list of absolute paths to every Makefile/Kbuild
                     file found under root_dir.
    """
    mapping     = {}
    kbuild_list = []

    if not root_dir or not os.path.isdir(root_dir):
        return {}, []

    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for name in filenames:
            if name not in ('Makefile', 'Kbuild'):
                continue
            abs_path = os.path.join(dirpath, name)
            kbuild_list.append(abs_path)
            rel_dir  = os.path.relpath(dirpath, root_dir)
            try:
                with io.open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        m = OBJ_LINE_RE.match(line)
                        if not m:
                            continue
                        selector = m.group(1)
                        rhs      = m.group(2)
                        if 'CONFIG_' not in selector:
                            continue
                        sym = (selector.split('$(')[-1].rstrip(')')
                               if '$(' in selector else None)
                        if not sym or not sym.startswith('CONFIG_'):
                            continue
                        for token in rhs.split():
                            if token.endswith('.o'):
                                src     = token[:-2] + '.c'
                                rel_src = os.path.normpath(
                                    os.path.join(rel_dir, src))
                                mapping.setdefault(sym, set()).add(rel_src)
            except (IOError, OSError):
                pass

    config_to_paths = dict((k, sorted(v)) for k, v in mapping.items())
    return config_to_paths, sorted(kbuild_list)


# ── backward-compat wrappers ─────────────────────────────────────────────────

def scan_makefile_config_map(root_dir):
    """Return config_to_paths dict (calls scan_kbuild_tree internally)."""
    config_to_paths, _ = scan_kbuild_tree(root_dir)
    return config_to_paths


def scan_kbuild_makefiles_list(root_dir):
    """Return sorted list of Makefile/Kbuild paths (calls scan_kbuild_tree)."""
    _, kbuild_files = scan_kbuild_tree(root_dir)
    return kbuild_files
