"""Output-only renderers for companion results (v21.7.0)."""
import csv
import io
import json

FORMATS = ('text', 'raw', 'csv', 'json', 'markdown')


def cell(value):
    if value is None:
        return ''
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool)) else str(value)


def render(value, fmt):
    if fmt in ('json', 'text'):
        return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    rows = value if isinstance(value, list) else [value]
    if fmt == 'raw':
        return ''.join(cell(row.get('commit', row) if isinstance(row, dict) else row) + '\n' for row in rows)
    if any(not isinstance(row, dict) for row in rows):
        rows = [dict(value=row) for row in rows]
    columns = list(dict.fromkeys(key for row in rows for key in row))
    if fmt == 'csv':
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows([[cell(row.get(key)) for key in columns] for row in rows])
        return stream.getvalue()
    def escape(value):
        return cell(value).replace('\\', '\\\\').replace('|', '\\|').replace('\r', '').replace('\n', '<br>')
    if not columns:
        return ''
    lines = ['| ' + ' | '.join(escape(key) for key in columns) + ' |',
             '| ' + ' | '.join('---' for _ in columns) + ' |']
    lines += ['| ' + ' | '.join(escape(row.get(key)) for key in columns) + ' |' for row in rows]
    return '\n'.join(lines) + '\n'
