from __future__ import print_function
import io
import os
import re


CONFIG_RE = re.compile(r'^(CONFIG_[A-Za-z0-9_]+)=(y|m|.+)$')
CONFIG_NOTSET_RE = re.compile(r'^# (CONFIG_[A-Za-z0-9_]+) is not set$')
OBJ_LINE_RE = re.compile(r'^(obj-[^\s:+?=]+)\s*[:+]?=\s*(.+)$')


def parse_kernel_config(path):
    enabled = {}
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


def scan_makefile_config_map(root_dir):
    mapping = {}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for name in filenames:
            if name not in ('Makefile', 'Kbuild'):
                continue
            path = os.path.join(dirpath, name)
            rel_dir = os.path.relpath(dirpath, root_dir)
            with io.open(path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    m = OBJ_LINE_RE.match(line)
                    if not m:
                        continue
                    selector = m.group(1)
                    rhs = m.group(2)
                    if 'CONFIG_' not in selector:
                        continue
                    config_symbol = selector.split('$(')[-1].rstrip(')') if '$(' in selector else None
                    if not config_symbol or not config_symbol.startswith('CONFIG_'):
                        continue
                    for token in rhs.split():
                        if token.endswith('.o'):
                            src = token[:-2] + '.c'
                            rel_src = os.path.normpath(os.path.join(rel_dir, src))
                            mapping.setdefault(config_symbol, set()).add(rel_src)
    return dict((k, sorted(v)) for k, v in mapping.items())
