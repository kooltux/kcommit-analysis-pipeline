from __future__ import print_function
import io
import os
import re


COMPILE_C_RE = re.compile(r'\b(?:CC|HOSTCC|AS|LD|AR|CXX)\b.*?([A-Za-z0-9_./+-]+\.(?:c|S|s|o|a|ko))')
YOCTO_PATCH_RE = re.compile(r'([A-Za-z0-9_./+-]+\.patch)')


def parse_build_log(path):
    result = {'compiled_sources': set(), 'built_objects': set(), 'modules': set()}
    if not path or not os.path.exists(path):
        return finalize(result)
    with io.open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = COMPILE_C_RE.search(line)
            if not m:
                continue
            token = m.group(1)
            if token.endswith('.c'):
                result['compiled_sources'].add(token)
            elif token.endswith('.o'):
                result['built_objects'].add(token)
            elif token.endswith('.ko'):
                result['modules'].add(token)
    return finalize(result)


def parse_yocto_log(path):
    result = {'patches': set(), 'mentions': []}
    if not path or not os.path.exists(path):
        return {'patches': [], 'mentions': []}
    with io.open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = YOCTO_PATCH_RE.search(line)
            if m:
                result['patches'].add(m.group(1))
            if 'linux' in line.lower() or 'kernel' in line.lower():
                result['mentions'].append(line.strip())
                if len(result['mentions']) > 2000:
                    result['mentions'] = result['mentions'][:2000]
                    break
    return {'patches': sorted(result['patches']), 'mentions': result['mentions']}


def scan_build_dir(build_dir):
    result = {'objects': set(), 'modules': set()}
    if not build_dir or not os.path.isdir(build_dir):
        return {'objects': [], 'modules': []}
    for dirpath, dirnames, filenames in os.walk(build_dir):
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), build_dir)
            if name.endswith('.o'):
                result['objects'].add(rel)
            elif name.endswith('.ko'):
                result['modules'].add(rel)
    return {'objects': sorted(result['objects']), 'modules': sorted(result['modules'])}


def finalize(result):
    return dict((k, sorted(v)) for k, v in result.items())
