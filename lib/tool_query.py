"""Shared JMESPath evaluation, validation and presentation (v21.7.0)."""


class QueryError(ValueError):
    pass


def compile_query(text):
    try:
        import jmespath
    except ImportError as exc:
        raise QueryError('Install dependencies: python3 -m pip install -r requirements.txt') from exc
    try:
        return jmespath.compile(text)
    except (jmespath.exceptions.JMESPathError, RecursionError) as exc:
        raise QueryError(str(exc)) from exc


def evaluate(query, row):
    import jmespath
    try:
        return query.search(row)
    except (jmespath.exceptions.JMESPathError, RecursionError) as exc:
        raise QueryError(str(exc)) from exc


class Predicates:
    def __init__(self, texts):
        self.queries = [(text, compile_query(text)) for text in texts]

    def result(self, row):
        values = []
        for text, query in self.queries:
            try:
                value = evaluate(query, row)
                if value is not None and type(value) is not bool:
                    raise QueryError('Expected boolean or null, got ' + type(value).__name__)
            except QueryError as exc:
                raise QueryError('%s: %s: %s' % (row.get('commit', '<record>'), text, exc)) from exc
            values.append(value)
        return False if False in values else None if None in values else True


def validate(rows, predicates, sample=None, explain=False, limit=10):
    selected = rows if sample is None else rows[:sample]
    report = dict(syntax='valid', population=len(rows), evaluated=len(selected),
                  sampled=sample is not None, evaluation_complete=len(selected) == len(rows),
                  matched=0, not_matched=0, null=0, errors=0, explanations=[], warnings=[])
    for row in selected:
        try:
            value = predicates.result(row)
            key = 'null' if value is None else 'matched' if value else 'not_matched'
            detail = dict(commit=row.get('commit'), result=value)
        except QueryError as exc:
            key, detail = 'errors', dict(commit=row.get('commit'), error=str(exc))
            report.setdefault('first_error', detail)
        report[key] += 1
        if explain and len(report['explanations']) < limit:
            report['explanations'].append(detail)
    report['evaluation'] = 'failed' if report['errors'] else 'completed' if selected else 'not_run'
    if not selected:
        report['warnings'].append('No records evaluated; runtime behavior is unverified.')
    elif report['null'] == len(selected):
        report['warnings'].append('All results are null; check paths and availability.')
    if not report['evaluation_complete']:
        report['warnings'].append('Records outside the sample were not validated.')
    return report


def present(rows, sort=None, reverse=False, project=None, limit=None):
    rows = list(rows)
    if sort is not None:
        query = compile_query(sort)
        pairs = [(evaluate(query, row), row) for row in rows]
        available = [(key, row) for key, row in pairs if key is not None]
        types = {'number' if type(key) in (int, float) else type(key).__name__ for key, _ in available}
        if not types <= {'number', 'str'} or len(types) > 1:
            raise QueryError('--sort requires uniformly numbers or strings; nulls sort last')
        rows = [row for _, row in sorted(available, key=lambda pair: pair[0], reverse=reverse)]
        rows += [row for key, row in pairs if key is None]
    elif reverse:
        rows.reverse()
    if limit is not None:
        rows = rows[:limit]
    if project is not None:
        query = compile_query(project)
        rows = [evaluate(query, row) for row in rows]
    return rows
