"""Isolated, non-destructive application simulations for commits (v21.7.0).

Index simulation uses a private temporary index; cherry-pick simulation uses a
disposable detached worktree.  Neither touches the user's branches, index or
working files.  The worktree method adds and removes temporary worktree
metadata in the repository's Git directory.
"""
import os
import shutil
import subprocess
import tempfile

OUTCOMES = ('clean', 'no_change', 'conflict', 'unsupported', 'error', 'not_tested')
CONFLICT_TEXT = ('patch failed', 'does not apply', 'with conflicts', 'does not exist in index',
                 'already exists in index', 'does not match index',
                 'lacks the necessary blob', 'could not apply', 'conflict')
IDENTITY = {'GIT_COMMITTER_NAME': 'kcommit-tool', 'GIT_COMMITTER_EMAIL': 'kcommit-tool@invalid'}


class CheckError(ValueError):
    pass


def git(cfg, args, data=None, env=None, cwd=None):
    binary = (cfg.get('collect') or {}).get('git_binary', 'git')
    environment = dict(os.environ)
    environment.update(env or {})
    environment['GIT_OPTIONAL_LOCKS'] = '0'
    proc = subprocess.run([binary, '-C', cwd or cfg['kernel']['source_dir']] + list(args),
                          input=data, capture_output=True, env=environment)
    return proc.returncode, proc.stdout, proc.stderr


def need(cfg, args, data=None, env=None, cwd=None):
    code, out, err = git(cfg, args, data, env, cwd)
    if code:
        raise CheckError('git %s failed: %s' % (args[0] if args else '', err.decode('utf-8', 'replace').strip()))
    return out


def text(data):
    return data.decode('utf-8', 'replace').strip()


def resolve_target(cfg, rev):
    sha = text(need(cfg, ['rev-parse', '--verify', '--end-of-options', rev + '^{commit}']))
    if len(sha) not in (40, 64):
        raise CheckError('Git did not resolve a full commit ID for target: ' + rev)
    return sha


def plan(cfg, shas, rev):
    """Resolve the target and return ancestor-first entries; never adds unselected commits."""
    target = resolve_target(cfg, rev)
    unique = list(dict.fromkeys(shas))
    given = {sha: number for number, sha in enumerate(unique)}
    kinds = {}
    if unique:
        listing = need(cfg, ['cat-file', '--batch-check'], ''.join(s + '\n' for s in unique).encode())
        for line in listing.decode('utf-8', 'replace').splitlines():
            fields = line.split()
            kinds[fields[0]] = fields[1] if len(fields) > 1 else 'missing'
    present = [sha for sha in unique if kinds.get(sha) == 'commit']
    parents, rank = {}, {}
    if present:
        data = ''.join(s + '\n' for s in present).encode()
        for line in need(cfg, ['rev-list', '--parents', '--no-walk=unsorted', '--stdin'], data).decode().splitlines():
            fields = line.split()
            parents[fields[0]] = len(fields) - 1
        walk = need(cfg, ['rev-list', '--topo-order', '--reverse', '--stdin'],
                    (''.join(s + '\n' for s in present) + '^' + target + '\n').encode())
        rank = {sha: number for number, sha in enumerate(walk.decode().split())}
    present.sort(key=lambda sha: (sha in rank, rank.get(sha, 0), given[sha]))
    entries = []
    for sha in present:
        entry = dict(commit=sha, parents=parents.get(sha, 0), in_target=sha not in rank)
        if entry['parents'] > 1:
            entry.update(preset='unsupported', diagnostic='merge commit: no mainline policy is defined')
        entries.append(entry)
    for sha in unique:
        if sha not in present:
            entries.append(dict(commit=sha, parents=None, in_target=False, preset='error',
                                diagnostic='object is %s, not a commit' % kinds.get(sha, 'missing')))
    for number, entry in enumerate(entries, 1):
        entry['position'] = number
    return dict(target=target, entries=entries)


def unmerged(cfg, args, env=None, cwd=None):
    code, out, _ = git(cfg, args, env=env, cwd=cwd)
    paths = []
    for item in out.split(b'\0'):
        if item:
            path = item.split(b'\t', 1)[-1].decode('utf-8', 'replace')
            if path not in paths:
                paths.append(path)
    return paths


def looks_like_conflict(diagnostic):
    lowered = diagnostic.lower()
    return any(marker in lowered for marker in CONFLICT_TEXT)


class IndexRunner:
    def __init__(self, cfg, target, mode):
        self.cfg, self.target, self.series = cfg, target, mode == 'series'

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix='kcommit-index-')
        self.index, self.backup = os.path.join(self.dir, 'index'), os.path.join(self.dir, 'backup')
        self.env = {'GIT_INDEX_FILE': self.index}
        try:
            need(self.cfg, ['read-tree', self.target], env=self.env)
            self.tree = self.base = text(need(self.cfg, ['write-tree'], env=self.env))
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    def restore(self, tree):
        shutil.copyfile(self.backup, self.index)
        code, out, _ = git(self.cfg, ['write-tree'], env=self.env)
        return 'verified' if code == 0 and text(out) == tree else 'failed'

    def attempt(self, sha):
        before = self.tree
        code, patch, err = git(self.cfg, ['diff-tree', '-p', '--binary', '--full-index', '--no-ext-diff',
                                          '--no-textconv', '-r', '--root', '--no-commit-id', sha])
        if code:
            return dict(outcome='error', diagnostic=text(err), recovery='not_needed', tree_before=before, tree_after=before)
        if not patch.strip():
            return dict(outcome='no_change', diagnostic='empty patch', recovery='not_needed', tree_before=before, tree_after=before)
        shutil.copyfile(self.index, self.backup)
        code, _, err = git(self.cfg, ['apply', '--cached', '--3way', '--whitespace=nowarn'], patch, env=self.env)
        if code == 0:
            after = text(need(self.cfg, ['write-tree'], env=self.env))
            result = dict(outcome='clean' if after != before else 'no_change', diagnostic='', recovery='not_needed',
                          tree_before=before, tree_after=after, conflicts=[])
            if self.series:
                self.tree = after
            else:
                result['recovery'] = self.restore(before)
            return result
        paths = unmerged(self.cfg, ['ls-files', '-u', '-z'], env=self.env)
        diagnostic = text(err)
        outcome = 'conflict' if paths or looks_like_conflict(diagnostic) else 'error'
        recovery = self.restore(before)
        if recovery != 'verified':
            outcome = 'error'
        return dict(outcome=outcome, diagnostic=diagnostic, recovery=recovery, tree_before=before, tree_after=before,
                    conflicts=paths if paths else None)


class WorktreeRunner:
    def __init__(self, cfg, target, mode, identity=IDENTITY, disable_signing=True, pick_args=(), record=False):
        self.cfg, self.target, self.series = cfg, target, mode == 'series'
        self.identity, self.disable_signing, self.pick_args, self.record = identity, disable_signing, list(pick_args), record

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix='kcommit-worktree-')
        self.path = os.path.join(self.dir, 'tree')
        hooks = os.path.join(self.dir, 'hooks')
        os.mkdir(hooks)
        self.options = ['-c', 'core.hooksPath=' + hooks, '-c', 'rerere.enabled=false',
                        '-c', 'advice.detachedHead=false']
        if self.disable_signing:
            self.options += ['-c', 'commit.gpgsign=false']
        self.added = False
        try:
            need(self.cfg, ['worktree', 'add', '--detach', self.path, self.target])
            self.added = True
            self.head, self.tree = self.target, self.rev('HEAD^{tree}')
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc):
        if self.added:
            git(self.cfg, ['worktree', 'remove', '--force', self.path])
        shutil.rmtree(self.dir, ignore_errors=True)
        git(self.cfg, ['worktree', 'prune'])
        return False

    def run(self, args):
        return git(self.cfg, self.options + list(args), env=self.identity, cwd=self.path)

    def rev(self, name):
        return text(self.run(['rev-parse', name])[1])

    def pristine(self, head):
        return self.rev('HEAD') == head and not self.run(['status', '--porcelain'])[1].strip()

    def reset(self, head):
        self.run(['reset', '--hard', head])
        self.run(['clean', '-fdq'])
        return 'verified' if self.pristine(head) else 'failed'

    def abort(self, head):
        self.run(['cherry-pick', '--abort'])
        if self.pristine(head):
            return 'verified'
        return 'reset' if self.reset(head) == 'verified' else 'failed'

    def attempt(self, sha):
        before_head, before_tree = self.head, self.tree
        code, out, err = self.run(['cherry-pick'] + self.pick_args + [sha])
        if code == 0:
            head, tree = self.rev('HEAD'), self.rev('HEAD^{tree}')
            result = dict(outcome='clean' if tree != before_tree else 'no_change', diagnostic='', recovery='not_needed',
                          tree_before=before_tree, tree_after=tree, conflicts=[])
            if self.record:
                result['new_commit'] = head
            if self.series:
                self.head, self.tree = head, tree
            else:
                result['recovery'] = self.reset(before_head)
            return result
        paths = unmerged(self.cfg, self.options + ['diff', '--name-only', '--diff-filter=U', '-z'],
                         env=self.identity, cwd=self.path)
        diagnostic = (text(err) + '\n' + text(out)).strip()
        lowered = diagnostic.lower()
        if paths:
            outcome = 'conflict'
        elif 'empty' in lowered or 'nothing to commit' in lowered:
            outcome = 'no_change'
        elif looks_like_conflict(diagnostic):
            outcome = 'conflict'
        else:
            outcome = 'error'
        recovery = self.abort(before_head)
        if recovery == 'failed':
            outcome = 'error'
        return dict(outcome=outcome, diagnostic=diagnostic, recovery=recovery, tree_before=before_tree,
                    tree_after=before_tree, conflicts=paths if paths else None)


RUNNERS = {'index': IndexRunner, 'cherry-pick': WorktreeRunner}


def run_entries(runner, entries, on_conflict='skip', progress=None):
    counts = dict.fromkeys(OUTCOMES, 0)
    results, stopped, failed = [], False, False
    for entry in entries:
        row = dict(commit=entry['commit'], position=entry['position'], in_target=entry['in_target'],
                   parents=entry['parents'], outcome='not_tested', conflicts=None, conflict_count=None,
                   diagnostic='', recovery='not_needed', tree_before=None, tree_after=None, new_commit=None)
        if not stopped:
            if entry.get('preset'):
                row.update(outcome=entry['preset'], diagnostic=entry['diagnostic'])
            else:
                row.update(runner.attempt(entry['commit']))
                failed = row['outcome'] == 'error'
                stopped = failed or (row['outcome'] == 'conflict' and on_conflict == 'stop')
        row['conflict_count'] = None if row['conflicts'] is None else len(row['conflicts'])
        counts[row['outcome']] += 1
        results.append(row)
        if progress:
            progress(dict(position=row['position'], total=len(entries), commit=row['commit'],
                          outcome=row['outcome'], counts=dict(counts)))
    return dict(results=results, counts=counts, stopped=stopped, execution_complete=not failed)


def execute(cfg, prepared, mode='series', method='index', on_conflict='skip', progress=None):
    with RUNNERS[method](cfg, prepared['target'], mode) as runner:
        return run_entries(runner, prepared['entries'], on_conflict, progress)
