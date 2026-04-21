from __future__ import print_function
import io
import os
import re


COMPAT_RE = re.compile(r'compatible\s*=\s*([^;]+);')
STATUS_OK_RE = re.compile(r'status\s*=\s*"okay"\s*;')
INCLUDE_RE = re.compile(r'#include\s+["<]([^">]+)[">]')
STRING_RE = re.compile(r'"([^"]+)"')


def scan_dts_roots(roots):
    result = {
        'dts_files': [],
        'compatible_strings': set(),
        'okay_files': set(),
        'includes': {}
    }
    for root in roots or []:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            for name in filenames:
                if not (name.endswith('.dts') or name.endswith('.dtsi')):
                    continue
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, root)
                result['dts_files'].append(rel)
                text = read_text(path)
                for m in COMPAT_RE.finditer(text):
                    for s in STRING_RE.findall(m.group(1)):
                        result['compatible_strings'].add(s)
                if STATUS_OK_RE.search(text):
                    result['okay_files'].add(rel)
                incs = INCLUDE_RE.findall(text)
                if incs:
                    result['includes'][rel] = incs
    return {
        'dts_files': sorted(result['dts_files']),
        'compatible_strings': sorted(result['compatible_strings']),
        'okay_files': sorted(result['okay_files']),
        'includes': result['includes']
    }


def read_text(path):
    with io.open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()
