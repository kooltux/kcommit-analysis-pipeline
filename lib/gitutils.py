"""Git helpers for kcommit-analysis-pipeline.

run_git() uses subprocess.run() with capture_output=True on Python >= 3.7
(available since 3.7; Ubuntu 18 ships Python 3.6, so we branch on the version).
"""
import os
import subprocess
import sys

_PY37 = sys.version_info >= (3, 7)

RS = u'\x1e'   # ASCII Record Separator  — git format delimiter
FS = u'\x1f'   # ASCII Unit Separator    — head/tail delimiter within a record


def run_git(cfg, args, check=True):
    collect = cfg.get('collect', {}) or {}
    git_bin = collect.get('git_binary', 'git')
    src     = cfg['kernel']['source_dir']
    cmd     = [git_bin, '-C', src] + args

    if _PY37:
        result = subprocess.run(cmd, capture_output=True, text=True)
        out, err, rc = result.stdout, result.stderr, result.returncode
    else:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
        out, err = p.communicate()
        rc = p.returncode

    if check and rc != 0:
        raise RuntimeError('git command failed (%s): %s' % (rc, err.strip()))
    return out


def iter_git_log_records(cfg):
    kernel  = cfg['kernel']
    collect = cfg.get('collect', {}) or {}
    rev_range = '%s..%s' % (kernel['rev_old'], kernel['rev_new'])
    fmt = (RS + 'commit=%H%nparents=%P%nauthor_time=%at%ncommit_time=%ct'
               '%nauthor_name=%an%nauthor_email=%ae%nsubject=%s%nbody=%B' + FS)
    args = ['log', rev_range, '--reverse', '--topo-order', '--format=' + fmt]

    # Config key is 'no_merges' (canonical). Support 'use_no_merges' as a
    # transparent fallback so configs written before the rename still work.
    no_merges = collect.get('no_merges', True)
    if no_merges:
        args.append('--no-merges')
    if collect.get('first_parent'):
        args.append('--first-parent')
    if collect.get('use_numstat', True):
        args.append('--numstat')
    elif collect.get('use_name_only', True):
        args.append('--name-only')
    args.extend(collect.get('extra_git_log_args', []))

    output = run_git(cfg, args)
    for raw in output.split(RS):
        raw = raw.strip()
        if not raw:
            continue
        if FS in raw:
            head, tail = raw.split(FS, 1)
        else:
            head, tail = raw, ''
        rec = parse_pretty_block(head)
        files, numstat = parse_tail_block(tail)
        rec['files']   = files
        rec['numstat'] = numstat
        yield rec


def parse_pretty_block(text):
    """Parse the key=value header block produced by iter_git_log_records."""
    record = {'body': '', 'files': [], 'numstat': []}
    body_lines = []
    in_body = False

    for line in text.splitlines():
        if in_body:
            body_lines.append(line)
            continue
        key, sep, val = line.partition('=')
        if not sep:
            continue
        if key == 'commit':
            record['commit'] = val
        elif key == 'parents':
            record['parents'] = [x for x in val.split() if x]
        elif key == 'author_time':
            record['author_time'] = int(val) if val else 0
        elif key == 'commit_time':
            record['commit_time'] = int(val) if val else 0
        elif key == 'author_name':
            record['author_name'] = val
        elif key == 'author_email':
            record['author_email'] = val
        elif key == 'subject':
            record['subject'] = val
        elif key == 'body':
            in_body = True
            body_lines.append(val)

    record['body'] = ' '.join(body_lines).strip()
    return record


def parse_tail_block(text):
    files   = []
    numstat = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) == 3 and (parts[0].isdigit() or parts[0] == '-'):
            numstat.append({'added': parts[0], 'deleted': parts[1], 'path': parts[2]})
            files.append(parts[2])
        elif len(parts) == 1:
            files.append(parts[0])
    return sorted(set(files)), numstat


def show_commit_patch(cfg, sha, unified=0):
    args = ['show', '--no-renames', '--format=medium', '--unified=%d' % unified, sha]
    return run_git(cfg, args)


def list_rev_commits(cfg):
    kernel  = cfg['kernel']
    collect = cfg.get('collect', {}) or {}
    rev_range = '%s..%s' % (kernel['rev_old'], kernel['rev_new'])
    args = ['rev-list', '--reverse', rev_range]
    no_merges = collect.get('no_merges', True)
    if no_merges:
        args.append('--no-merges')
    if collect.get('first_parent'):
        args.append('--first-parent')
    out = run_git(cfg, args)
    return [x.strip() for x in out.splitlines() if x.strip()]


def show_path_history(cfg, rev, path):
    args = ['show', '%s:%s' % (rev, path)]
    try:
        return run_git(cfg, args, check=False)
    except Exception:
        return ''
