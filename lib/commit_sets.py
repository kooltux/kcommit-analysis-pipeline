#!/usr/bin/env python3
"""Read-only commit-set queries for output/scripts/list_commits.py (v21.6.0)."""
import json
import os
import re
import sys

FILES = {
    'all': 'commits.json', 'related': 'prefilter_kept_commits.json',
    'scored': 'scored_commits.json', 'relevant': 'relevant_commits.json',
    'below_threshold': 'postfilter_dropped_commits.json',
}
NAMES = ('all', 'related', 'scored', 'relevant', 'prefilter_rejected',
         'below_threshold', 'filtered', 'displayed')
VARIABLE = re.compile(r'\$\{(env:)?([A-Za-z_][A-Za-z0-9_]*)\}')
SHA = re.compile(r'[0-9a-f]{40}')
HELP = """Usage: list_commits.py [--sets | SET | --expr 'EXPRESSION']
No arguments, -h, --help: usage followed by the commit-set tree.
--sets: tree only. SET/--expr: full SHAs only, one per line.
Operators (highest first): ~ ; & and - (left to right) ; ^ ; |.
Parentheses group expressions. Complement ~ is relative to all.
Examples: --expr 'related - relevant'
          --expr '(prefilter_rejected | below_threshold) & ~displayed'
Sets: all=collected; related=prefilter kept; scored=Stage 05;
      relevant=Stage 06 kept; prefilter_rejected=all-related;
      below_threshold=Stage 06 drops; filtered=related-relevant;
      displayed=actual relevant report selection (possibly top-N).
Uses ../pipeline_config.json relative to this script, then configured paths.
all respects collection limits; report top-N affects displayed, not all.
Unavailable inputs are not empty sets. Queries require a valid all universe.
Results are unique and retain all's collection order. No Git calls or writes.
Exit: 0 success, 1 unavailable/invalid data, 2 invalid command/expression.
"""


class Unavailable(ValueError):
    pass


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('non-JSON constant: ' + value)
    with open(path, encoding='utf-8') as stream:
        return json.load(stream, object_pairs_hook=unique, parse_constant=constant)


def directories(config, base):
    variables = dict(config.get('vars') or {})
    variables.setdefault('CONFIGDIR', base)
    variables.setdefault('CWD', os.getcwd())
    for name in ('WORKSPACE', 'TOOLDIR'):
        if os.environ.get(name):
            variables.setdefault(name, os.environ[name])
    def expand(text, stack=()):
        if len(stack) > 64:
            raise ValueError('variable expansion too deep')
        def replace(match):
            env, name = match.groups()
            key = ('env:' if env else '') + name
            if key in stack:
                raise ValueError('cyclic variable: ' + key)
            source = os.environ if env else variables
            if name not in source or source[name] in (None, ''):
                raise ValueError('undefined/empty variable: ' + key)
            return expand(str(source[name]), stack + (key,))
        value = VARIABLE.sub(replace, text)
        if '${' in value:
            raise ValueError('unresolved variable in path')
        return value
    paths = config.get('paths')
    if not isinstance(paths, dict):
        raise ValueError('configuration requires paths')
    result = []
    for key in ('cache_dir', 'output_dir'):
        value = paths.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('configuration requires paths.' + key)
        value = expand(value)
        result.append(os.path.abspath(os.path.join(base, value)))
    return result


def ids(path):
    values = load_json(path)
    if not isinstance(values, list):
        raise ValueError('expected a JSON array: ' + path)
    ordered, seen = [], set()
    for item in values:
        sha = item.get('commit') if isinstance(item, dict) else None
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise ValueError('invalid full commit SHA in ' + path)
        if sha not in seen:
            seen.add(sha)
            ordered.append(sha)
    return ordered


def read_sets(script_path):
    base = os.path.dirname(os.path.dirname(os.path.abspath(script_path)))
    config = load_json(os.path.join(base, 'pipeline_config.json'))
    if not isinstance(config, dict):
        raise ValueError('configuration must be a JSON object')
    cache, output = directories(config, base)
    sets, errors, order = {}, {}, []
    sources = [(name, os.path.join(cache, file)) for name, file in FILES.items()]
    sources.append(('displayed', os.path.join(output, 'relevant_commits.json')))
    for name, path in sources:
        try:
            values = ids(path)
            sets[name] = set(values)
            if name == 'all':
                order = values
        except (OSError, ValueError) as exc:
            errors[name] = str(exc)
    for child, parent in [('related', 'all'), ('scored', 'all'), ('relevant', 'all'),
                          ('below_threshold', 'all'), ('displayed', 'all'),
                          ('scored', 'related'), ('relevant', 'related'), ('below_threshold', 'related'),
                          ('relevant', 'scored'),
                          ('below_threshold', 'scored'), ('displayed', 'relevant')]:
        if child in sets and parent in sets and not sets[child] <= sets[parent]:
            errors[child] = child + ' is not a subset of ' + parent
            del sets[child]
    if 'relevant' in sets and 'below_threshold' in sets:
        kept, dropped = sets['relevant'], sets['below_threshold']
        if kept & dropped or 'scored' in sets and kept | dropped != sets['scored']:
            for name in ('relevant', 'below_threshold'):
                errors[name] = 'Stage 06 kept/dropped do not partition scored'
                del sets[name]
    for name, left, right in [('prefilter_rejected', 'all', 'related'),
                              ('filtered', 'related', 'relevant')]:
        if left in sets and right in sets:
            sets[name] = sets[left] - sets[right]
        else:
            errors[name] = 'requires available ' + left + ' and ' + right
    for name in NAMES:
        if name in errors:
            sets.pop(name, None)
    return config, sets, errors, order


class Expression:
    PRECEDENCE = {'|': 10, '^': 20, '&': 30, '-': 30}

    def __init__(self, text, sets):
        self.sets, self.tokens, self.index = sets, [], 0
        while text.strip():
            match = re.match(r'\s*([a-z_][a-z0-9_]*|[|^&~()\-])', text)
            if not match:
                raise ValueError('invalid expression character')
            self.tokens.append(match.group(1))
            text = text[match.end():]
        if not self.tokens:
            raise ValueError('empty expression')

    def value(self, name):
        if name not in NAMES:
            raise ValueError('unknown set: ' + name)
        if name not in self.sets:
            raise Unavailable('unavailable set: ' + name)
        return self.sets[name]

    def parse(self, minimum=0, depth=0):
        if depth > 64:
            raise ValueError('expression nesting exceeds 64')
        if self.index >= len(self.tokens):
            raise ValueError('missing operand')
        token = self.tokens[self.index]
        self.index += 1
        if token == '~':
            left = self.value('all') - self.parse(40, depth + 1)
        elif token == '(':
            left = self.parse(0, depth + 1)
            if self.index >= len(self.tokens) or self.tokens[self.index] != ')':
                raise ValueError('missing closing parenthesis')
            self.index += 1
        elif token in NAMES:
            left = self.value(token)
        else:
            raise ValueError('unknown set or unexpected token: ' + token)
        while self.index < len(self.tokens):
            op = self.tokens[self.index]
            priority = self.PRECEDENCE.get(op, -1)
            if priority < minimum:
                break
            self.index += 1
            right = self.parse(priority + 1, depth + 1)
            if op == '|': left = left | right
            elif op == '^': left = left ^ right
            elif op == '&': left = left & right
            else: left = left - right
        return left

    def evaluate(self):
        result = self.parse()
        if self.index != len(self.tokens):
            raise ValueError('unexpected trailing token: ' + self.tokens[self.index])
        return result


def tree_lines(sets):
    """Present partitions without repeating equal intermediate sets."""
    notes = []
    related = sets.get('related')
    scored = sets.get('scored')
    relevant = sets.get('relevant')
    displayed = sets.get('displayed')
    report_children = []
    if relevant is not None and displayed is not None:
        if displayed == relevant:
            notes.append('Report complete: displayed = relevant')
        elif displayed <= relevant:
            report_children = [('not_displayed', relevant - displayed, []),
                               ('displayed', displayed, [])]
        else:
            notes.append('Report coverage: inconsistent displayed membership')
    else:
        notes.append('Report coverage: unavailable')
    scoring_children = [('below_threshold', sets.get('below_threshold'), []),
                        ('relevant', relevant, report_children)]
    if related is not None and scored is not None:
        if scored == related:
            notes.insert(0, 'Scoring complete: scored = related')
        elif scored <= related:
            scoring_children = [('unscored', related - scored, []),
                                ('scored', scored, scoring_children)]
        else:
            notes.insert(0, 'Scoring coverage: inconsistent scored membership')
    else:
        notes.insert(0, 'Scoring coverage: unavailable')
    root = ('all', sets.get('all'), [
        ('prefilter_rejected', sets.get('prefilter_rejected'), []),
        ('related', related, scoring_children)])
    lines = ['Commit sets:']
    def visit(node, prefix='', branch='', child_prefix=''):
        name, members, children = node
        label = prefix + branch + name
        count = len(members) if members is not None else 'unavailable'
        lines.append('{:<28} {}'.format(label, count))
        for index, child in enumerate(children):
            last = index == len(children) - 1
            visit(child, child_prefix, '└── ' if last else '├── ',
                  child_prefix + ('    ' if last else '│   '))
    visit(root)
    return lines + [''] + notes


def main(argv=None, script_path=None):
    argv = sys.argv[1:] if argv is None else argv
    help_mode = not argv or argv in (['-h'], ['--help'])
    listing = help_mode or argv == ['--sets']
    if help_mode:
        print(HELP)
    if not listing and not (len(argv) == 1 and argv[0] in NAMES or
                            len(argv) == 2 and argv[0] == '--expr'):
        print(HELP, file=sys.stderr)
        return 2
    try:
        config, sets, errors, order = read_sets(script_path or __file__)
    except (OSError, ValueError, TypeError) as exc:
        sets, errors, order = {}, dict.fromkeys(NAMES, str(exc)), []
    if listing:
        print('\n'.join(tree_lines(sets)))
    else:
        try:
            result = Expression(argv[0] if len(argv) == 1 else argv[1], sets).evaluate()
            if 'all' not in sets:
                raise Unavailable('unavailable all universe')
            if not result <= sets['all']:
                raise Unavailable('query result escapes all universe')
            if result:
                print('\n'.join(sha for sha in order if sha in result))
            return 0
        except Unavailable as exc:
            print('Error: ' + str(exc), file=sys.stderr)
            return 1
        except ValueError as exc:
            print('Error: ' + str(exc), file=sys.stderr)
            return 2
    for name in NAMES:
        if name in errors:
            print(name + ': ' + errors[name], file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
