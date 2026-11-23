"""Real cherry-picks onto a branch, published atomically (v21.7.0).

Picks run in a disposable detached worktree; the branch moves only at the end,
with a single compare-and-swap ``update-ref``.  The user's checkout, index,
HEAD and files are never touched.
"""
from lib import tool_check as tc

BLOCKING = ('conflict', 'unsupported', 'error', 'not_tested')


class ApplyError(ValueError):
    pass


def checked_out_refs(cfg):
    listing = tc.text(tc.need(cfg, ['worktree', 'list', '--porcelain']))
    return {line[7:] for line in listing.splitlines() if line.startswith('branch ')}


def check_identity(cfg):
    code, _, err = tc.git(cfg, ['var', 'GIT_COMMITTER_IDENT'])
    if code:
        raise ApplyError('Git committer identity is not configured: ' + tc.text(err))


def resolve_destination(cfg, branch=None, new_branch=None, target=None, default_rev=None):
    if bool(branch) == bool(new_branch):
        raise ApplyError('Use exactly one of --branch or --new-branch')
    if branch and target:
        raise ApplyError('--target applies only with --new-branch')
    name = branch or new_branch
    ref = 'refs/heads/' + name
    if name.startswith('-') or tc.git(cfg, ['check-ref-format', ref])[0]:
        raise ApplyError('Invalid branch name: ' + name)
    code, out, _ = tc.git(cfg, ['rev-parse', '--verify', '--quiet', ref + '^{commit}'])
    old = tc.text(out) if code == 0 else None
    if branch:
        if old is None:
            raise ApplyError('Branch does not exist: ' + name)
        base = old
    else:
        if old is not None:
            raise ApplyError('Branch already exists: ' + name)
        rev = target or default_rev
        if not rev:
            raise ApplyError('Provide --target or configure kernel.rev_old')
        base = tc.resolve_target(cfg, rev)
    if ref in checked_out_refs(cfg):
        raise ApplyError('Branch is checked out in a worktree; check out another branch first: ' + name)
    return dict(kind='existing' if branch else 'new', name=name, ref=ref, base=base, old_tip=old)


def publish(cfg, dest, new_tip):
    """Move or create the branch only if it still has the tip observed at the start."""
    try:
        if dest['ref'] in checked_out_refs(cfg):
            raise ApplyError('Branch became checked out during the run: ' + dest['name'])
        tc.need(cfg, ['update-ref', '-m', 'kcommit-tool apply', dest['ref'], new_tip,
                      dest['old_tip'] or '0' * len(new_tip)])
    except (tc.CheckError, ApplyError) as exc:
        return False, 'branch changed during the run or could not be updated: %s' % exc
    return True, 'published'


def apply(cfg, prepared, dest, on_conflict='stop', publish_policy='complete', record_origin=True, progress=None):
    def relabel(event):
        event = dict(event)
        counts = dict(event['counts'])
        counts['applied'] = counts.pop('clean')
        event['counts'] = counts
        if event['outcome'] == 'clean':
            event['outcome'] = 'applied'
        if progress:
            progress(event)

    options = ['-x'] if record_origin else []
    with tc.WorktreeRunner(cfg, dest['base'], 'series', identity={}, disable_signing=False,
                           pick_args=options, record=True) as runner:
        done = tc.run_entries(runner, prepared['entries'], on_conflict, relabel)
        counts = dict(done['counts'])
        counts['applied'] = counts.pop('clean')
        for row in done['results']:
            if row['outcome'] == 'clean':
                row['outcome'] = 'applied'
        blocked = sum(counts[name] for name in BLOCKING)
        new_tip, state = dest['old_tip'], 'noop'
        if not done['execution_complete']:
            published, reason, state = False, 'execution failed; nothing published', 'failed'
        elif publish_policy == 'complete' and blocked:
            published, state = False, 'blocked'
            reason = '%d commit(s) not applied; --publish complete requires all' % blocked
        elif counts['applied'] == 0:
            published, reason = False, 'no commit changed the tree; nothing to publish'
        else:
            published, reason = publish(cfg, dest, runner.head)
            state = 'published' if published else 'failed'
            new_tip = runner.head if published else dest['old_tip']
    return dict(results=done['results'], counts=counts, stopped=done['stopped'],
                execution_complete=done['execution_complete'], published=published, reason=reason,
                state=state, new_tip=new_tip)
