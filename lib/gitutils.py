import os
import subprocess


RS = u''
FS = u''


def run_git(cfg, args, check=True):
    collect = cfg.get('collect', {}) or {}
    git_bin = collect.get('git_binary', 'git')
    src = cfg['kernel']['source_dir']
    cmd = [git_bin, '-C', src] + args
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    out, err = p.communicate()
    if check and p.returncode != 0:
        raise RuntimeError('git command failed (%s): %s' % (p.returncode, err))
    return out


def iter_git_log_records(cfg):
    kernel = cfg['kernel']
    collect = cfg.get('collect', {}) or {}
    rev_range = '%s..%s' % (kernel['rev_old'], kernel['rev_new'])
    fmt = RS + 'commit=%H%nparents=%P%nauthor_time=%at%ncommit_time=%ct%nauthor_name=%an%nauthor_email=%ae%nsubject=%s%nbody=%B' + FS
    args = ['log', rev_range, '--reverse', '--topo-order', '--format=' + fmt]
    if collect.get('use_no_merges', True):
        args.append('--no-merges')
    if collect.get('use_first_parent'):
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
        rec['files'] = files
        rec['numstat'] = numstat
        yield rec


def parse_pretty_block(text):
    record = {'body': '', 'files': [], 'numstat': []}
    lines = text.splitlines()
    body_lines = []
    in_body = False
    for line in lines:
        if in_body:
            body_lines.append(line)
            continue
        if line.startswith('commit='):
            record['commit'] = line[len('commit='):]
        elif line.startswith('parents='):
            record['parents'] = [x for x in line[len('parents='):].split() if x]
        elif line.startswith('author_time='):
            record['author_time'] = int(line[len('author_time='):]) if line[len('author_time='):] else 0
        elif line.startswith('commit_time='):
            record['commit_time'] = int(line[len('commit_time='):]) if line[len('commit_time='):] else 0
        elif line.startswith('author_name='):
            record['author_name'] = line[len('author_name='):]
        elif line.startswith('author_email='):
            record['author_email'] = line[len('author_email='):]
        elif line.startswith('subject='):
            record['subject'] = line[len('subject='):]
        elif line.startswith('body='):
            in_body = True
            body_lines.append(line[len('body='):])
    record['body'] = ' '.join(body_lines).strip()
    return record


def parse_tail_block(text):
    files = []
    numstat = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('	')
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
    kernel = cfg['kernel']
    collect = cfg.get('collect', {}) or {}
    rev_range = '%s..%s' % (kernel['rev_old'], kernel['rev_new'])
    args = ['rev-list', '--reverse', rev_range]
    if collect.get('use_no_merges', True):
        args.append('--no-merges')
    if collect.get('use_first_parent'):
        args.append('--first-parent')
    out = run_git(cfg, args)
    return [x.strip() for x in out.splitlines() if x.strip()]


def show_path_history(cfg, rev, path):
    args = ['show', '%s:%s' % (rev, path)]
    try:
        return run_git(cfg, args, check=False)
    except Exception:
        return ''
