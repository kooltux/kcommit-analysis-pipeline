"""Content checks for resource files declared with ``content`` in CONFIG_SCHEMA.

v20.1.0: shared by ``validate`` (lib/validation.py) so that a resource that
Stage 08 or the report stages would reject is reported before the pipeline runs.
Every checker returns ``None`` when the file is acceptable, otherwise a short
human-readable problem string.
"""
import json


def _read_text(path):
    try:
        with open(path, 'rb') as stream:
            return stream.read().decode('utf-8'), None
    except (OSError, UnicodeError) as exc:
        return None, 'cannot be read as UTF-8 text ({})'.format(exc)


def check_text(path):
    return _read_text(path)[1]


def check_markdown(path):
    text, problem = _read_text(path)
    if problem:
        return problem
    if not text.strip():
        return 'is empty'
    return None


def check_json(path):
    text, problem = _read_text(path)
    if problem:
        return problem
    try:
        json.loads(text)
    except ValueError as exc:
        return 'is not valid JSON ({})'.format(exc)
    return None


def check_ai_result_schema(path):
    """Same acceptance rule as Stage 08: an object schema with properties.results."""
    text, problem = _read_text(path)
    if problem:
        return problem
    try:
        schema = json.loads(text)
    except ValueError as exc:
        return 'is not valid JSON ({})'.format(exc)
    props = schema.get('properties') if isinstance(schema, dict) else None
    if (not isinstance(schema, dict) or schema.get('type') != 'object'
            or not isinstance(props, dict) or 'results' not in props):
        return 'is not a valid AI result schema (object with properties.results)'
    return None


CHECKERS = {
    'text': check_text,
    'markdown': check_markdown,
    'json': check_json,
    'ai_result_schema': check_ai_result_schema,
}


def check_content(kind, path):
    """Run the checker registered for *kind*; unknown kinds are a schema bug."""
    return CHECKERS[kind](path)
