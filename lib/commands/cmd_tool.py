"""Companion exploration commands; never execute pipeline stages (v21.7.0)."""
import argparse
import json
from pathlib import Path
import sys

from lib import tool_apply, tool_check
from lib.commit_sets import NAMES
from lib.gitutils import run_git
from lib.tool_data import Dataset, configuration, fields
from lib.tool_output import FORMATS, render
from lib.tool_query import Predicates, QueryError, present, validate


def nonnegative(text):
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError('must be nonnegative')
    return value


def positive(text):
    value = nonnegative(text)
    if not value:
        raise argparse.ArgumentTypeError('must be positive')
    return value


def parser():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', required=True)
    ap.add_argument('--override', metavar='JSON')
    ap.add_argument('--repo', help='Override kernel.source_dir')
    ap.add_argument('--format', choices=FORMATS, default='text')
    ap.add_argument('--output', help='Create a new report; existing files are never overwritten')
    ap.add_argument('--progress', choices=('text', 'jsonl', 'off'), default='off')
    ap.add_argument('-v', '--verbose', action='count', default=0)
    commands = ap.add_subparsers(dest='command', required=True)
    descriptions = dict(summary='Result availability and imported AI counts', sets='Named populations',
                        fields='Nested query paths, types and availability', list='Select and display commits',
                        show='One commit and optional display patch', branches='Local branches',
                        check='Simulate applying selected commits without changing the repository',
                        apply='Cherry-pick selected commits onto a branch (published atomically)')
    descriptions['validate-filter'] = 'Compile filters and explain their results'
    for name, description in descriptions.items():
        command = commands.add_parser(name, help=description)
        if name in ('fields', 'list', 'validate-filter', 'check', 'apply'):
            command.add_argument('population', nargs='?', choices=NAMES)
            command.add_argument('--commits-file', metavar='FILE')
            command.add_argument('--list', action='append', default=[], metavar='NAME=FILE')
        if name in ('fields', 'list', 'validate-filter', 'branches', 'check', 'apply'):
            command.add_argument('--where', action='append', default=[], metavar='JMESPATH')
            command.add_argument('--filter-file', action='append', default=[], metavar='FILE')
        if name != 'validate-filter':
            command.add_argument('--project', metavar='JMESPATH')
            command.add_argument('--sort', metavar='JMESPATH')
            command.add_argument('--reverse', action='store_true')
            command.add_argument('--limit', type=nonnegative)
        if name == 'check':
            command.add_argument('--target', metavar='REV', help='Starting revision (default: kernel.rev_old)')
            command.add_argument('--mode', choices=('individual', 'series'), default='series')
            command.add_argument('--method', choices=('index', 'cherry-pick'), default='index')
            command.add_argument('--on-conflict', dest='on_conflict', choices=('stop', 'skip'), default='skip')
            command.add_argument('--dry-run', action='store_true', help='Resolve and preview; attempt nothing')
        if name == 'apply':
            command.add_argument('--branch', metavar='NAME', help='Existing branch to extend from its tip')
            command.add_argument('--new-branch', dest='new_branch', metavar='NAME', help='Branch to create at --target')
            command.add_argument('--target', metavar='REV', help='Base for --new-branch (default: kernel.rev_old)')
            command.add_argument('--on-conflict', dest='on_conflict', choices=('stop', 'skip'), default='stop')
            command.add_argument('--publish', choices=('complete', 'applied'), default='complete',
                                 help='complete: move the branch only if every commit applied')
            command.add_argument('--no-record-origin', dest='record_origin', action='store_false',
                                 help='Do not add the (cherry picked from commit ...) trailer')
            command.add_argument('--dry-run', action='store_true', help='Validate destination and order; change nothing')
        if name == 'show':
            command.add_argument('commit')
            command.add_argument('--patch', action='store_true')
        if name == 'validate-filter':
            command.add_argument('--sample', type=positive)
            command.add_argument('--explain', action='store_true')
            command.add_argument('--limit', type=nonnegative, default=10, help='Explanation limit, not evaluation limit')
    return ap


def progress(args, event, **values):
    if args.progress == 'jsonl':
        print(json.dumps(dict(event=event, **values)), file=sys.stderr)
    elif args.progress == 'text':
        print('kcommit-tool: %s %s' % (event, values), file=sys.stderr)


def execute(args):
    texts = list(getattr(args, 'where', []))
    texts += [Path(path).read_text(encoding='utf-8') for path in getattr(args, 'filter_file', [])]
    if args.command == 'validate-filter' and not texts:
        raise QueryError('Provide --where or --filter-file')
    predicates = Predicates(texts)
    cfg = configuration(args)
    progress(args, 'loading')
    if args.command == 'branches':
        text = run_git(cfg, ['for-each-ref', '--format=%(refname:short)%00%(objectname)%00%(HEAD)%00%(upstream:short)', 'refs/heads/'])
        rows = []
        for line in text.splitlines():
            name, commit, head, upstream = line.split('\x00')
            row = dict(name=name, commit=commit, current=head == '*', upstream=upstream or None)
            if predicates.result(row) is True:
                rows.append(row)
    else:
        data = Dataset(cfg)
        for warning in data.warnings:
            print('Warning: ' + warning, file=sys.stderr)
        if args.verbose:
            for name, reason in data.errors.items():
                print('Unavailable %s: %s' % (name, reason), file=sys.stderr)
        if args.command == 'summary':
            rows = [data.summary()]
        elif args.command == 'sets':
            rows = data.summary()['sets']
        elif args.command == 'show':
            row = data.record(data.resolve(args.commit))
            if args.patch:
                row['patch'] = run_git(cfg, ['show', '--format=', '--no-ext-diff', '--no-textconv', row['commit'], '--'])
            rows = [row]
        else:
            if args.commits_file and args.population:
                raise ValueError('Use a named population or --commits-file, not both')
            data.add_lists(args.list)
            name = args.population or ('all' if args.command == 'fields' else 'related')
            rows = data.population(name, args.commits_file)
            progress(args, 'selected', records=len(rows))
            if args.command == 'validate-filter':
                report = validate(rows, predicates, args.sample, args.explain, args.limit)
                return report, 2 if report['errors'] else 0
            rows = [row for row in rows if predicates.result(row) is True]
            if args.command == 'check':
                return check_command(args, cfg, rows)
            if args.command == 'apply':
                return apply_command(args, cfg, rows)
            if args.command == 'fields':
                rows = fields(rows)
    return present(rows, args.sort, args.reverse, args.project, args.limit), 0


def check_command(args, cfg, rows):
    """Preview or run an isolated simulation; --sort/--limit/--project shape the report only."""
    rev = args.target or (cfg.get('kernel') or {}).get('rev_old')
    if not rev:
        raise ValueError('Provide --target or configure kernel.rev_old')
    subjects = {row['commit']: row.get('subject') for row in rows}
    prepared = tool_check.plan(cfg, [row['commit'] for row in rows], rev)
    report = dict(target_requested=rev, target=prepared['target'], mode=args.mode, method=args.method,
                  on_conflict=args.on_conflict, selected=len(rows), dry_run=args.dry_run)
    progress(args, 'planned', target=prepared['target'], commits=len(prepared['entries']))
    if args.dry_run:
        results = [dict(position=e['position'], commit=e['commit'], subject=subjects.get(e['commit']),
                        in_target=e['in_target'], parents=e['parents'],
                        planned=e.get('preset', 'attempt'), diagnostic=e.get('diagnostic', ''))
                   for e in prepared['entries']]
        report.update(summary=None, stopped=False, execution_complete=None)
        status = 0
    else:
        done = tool_check.execute(cfg, prepared, args.mode, args.method, args.on_conflict,
                                  lambda event: progress(args, 'attempt', **event))
        results = done['results']
        for row in results:
            row['subject'] = subjects.get(row['commit'])
        report.update(summary=done['counts'], stopped=done['stopped'], execution_complete=done['execution_complete'])
        status = 0 if done['execution_complete'] else 1
    report['results'] = present(results, args.sort, args.reverse, args.project, args.limit)
    return report, status


def check_text(report):
    lines = ['Target: %s (%s)' % (report['target_requested'], report['target']),
             'Mode: %s, method: %s, on conflict: %s%s' % (report['mode'], report['method'], report['on_conflict'],
                                                      ' [dry run]' if report['dry_run'] else '')]
    if report['summary']:
        lines.append('Summary: ' + ', '.join('%s %d' % item for item in report['summary'].items()))
    for row in report['results']:
        label = row.get('outcome') or row.get('planned')
        extra = ' (%s file(s))' % row['conflict_count'] if row.get('conflict_count') else ''
        lines.append('%4s  %s  %s%s  %s' % (row['position'], row['commit'][:12], label, extra, row.get('subject') or ''))
    return '\n'.join(lines) + '\n'


def apply_command(args, cfg, rows):
    """Preview or perform real cherry-picks; exit 0 published/no-op, 3 blocked by policy, 1 failure."""
    tool_apply.check_identity(cfg)
    dest = tool_apply.resolve_destination(cfg, args.branch, args.new_branch, args.target,
                                          (cfg.get('kernel') or {}).get('rev_old'))
    subjects = {row['commit']: row.get('subject') for row in rows}
    prepared = tool_check.plan(cfg, [row['commit'] for row in rows], dest['base'])
    report = dict(destination=dest, publish_policy=args.publish, on_conflict=args.on_conflict,
                  record_origin=args.record_origin, selected=len(rows), dry_run=args.dry_run)
    progress(args, 'planned', destination=dest['name'], base=dest['base'], commits=len(prepared['entries']))
    if args.dry_run:
        results = [dict(position=e['position'], commit=e['commit'], subject=subjects.get(e['commit']),
                        in_target=e['in_target'], parents=e['parents'],
                        planned=e.get('preset', 'attempt'), diagnostic=e.get('diagnostic', ''))
                   for e in prepared['entries']]
        report.update(summary=None, stopped=False, execution_complete=None, published=False,
                      state='dry_run', reason='dry run', new_tip=None)
        status = 0
    else:
        done = tool_apply.apply(cfg, prepared, dest, args.on_conflict, args.publish, args.record_origin,
                                lambda event: progress(args, 'attempt', **event))
        results = done['results']
        for row in results:
            row['subject'] = subjects.get(row['commit'])
        report.update(summary=done['counts'], stopped=done['stopped'], execution_complete=done['execution_complete'],
                      published=done['published'], state=done['state'], reason=done['reason'], new_tip=done['new_tip'])
        status = dict(published=0, noop=0, blocked=3, failed=1)[done['state']]
    report['results'] = present(results, args.sort, args.reverse, args.project, args.limit)
    return report, status


def apply_text(report):
    dest = report['destination']
    lines = ['Destination: %s branch %s (base %s)' % (dest['kind'], dest['name'], dest['base']),
             'Policy: on conflict %s, publish %s, origin trailer %s%s' % (
                 report['on_conflict'], report['publish_policy'], 'on' if report['record_origin'] else 'off',
                 ' [dry run]' if report['dry_run'] else '')]
    if report['summary']:
        lines.append('Summary: ' + ', '.join('%s %d' % item for item in report['summary'].items()))
    for row in report['results']:
        label = row.get('outcome') or row.get('planned')
        lines.append('%4s  %s  %s  %s' % (row['position'], row['commit'][:12], label, row.get('subject') or ''))
    lines.append('Published: %s (%s)%s' % ('yes' if report['published'] else 'no', report['reason'],
                                         ', new tip ' + report['new_tip'] if report['published'] else ''))
    return '\n'.join(lines) + '\n'


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        value, status = execute(args)
        if args.command == 'list' and args.format == 'text' and args.project is None:
            text = ''.join('%s  %s  %s\n' % (row['commit'], row.get('score', ''), row.get('subject', '')) for row in value)
        elif args.command == 'check' and args.format == 'text' and args.project is None:
            text = check_text(value)
        elif args.command == 'apply' and args.format == 'text' and args.project is None:
            text = apply_text(value)
        elif args.command in ('check', 'apply') and args.format in ('raw', 'csv', 'markdown'):
            text = render(value['results'], args.format)
        else:
            text = render(value, args.format)
        if args.output:
            with open(args.output, 'x', encoding='utf-8', newline='') as stream:
                stream.write(text)
        else:
            sys.stdout.write(text)
        progress(args, 'complete', status=status)
        return status
    except KeyboardInterrupt:
        print('Interrupted; temporary state was cleaned up.', file=sys.stderr)
        return 130
    except QueryError as exc:
        print('Filter error: ' + str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 1
