"""Offline Draft 2020-12 validation of AI schema assets."""
import json
from pathlib import Path
import re
from urllib.parse import unquote

DRAFT = 'https://json-schema.org/draft/2020-12/schema'
SCHEMA_DIR = Path(__file__).resolve().parents[1] / 'configs' / 'ai' / 'schemas'
SCHEMA_NAMES = ('input', 'analyst', 'cve', 'reviewer', 'result')
_MAPS = ('$defs', 'definitions', 'properties', 'patternProperties', 'dependentSchemas')
_SINGLE = ('additionalProperties', 'unevaluatedProperties', 'unevaluatedItems',
           'propertyNames', 'contains', 'not', 'if', 'then', 'else', 'items', 'contentSchema')
_ARRAYS = ('allOf', 'anyOf', 'oneOf', 'prefixItems')


class SchemaDecodeError(ValueError):
    """Schema bytes cannot be decoded as strict UTF-8 JSON."""


def _where(parts):
    return '#' + ''.join('/' + str(p).replace('~', '~0').replace('/', '~1') for p in parts)


def _nodes(schema, path=()):
    yield path, schema
    if not isinstance(schema, dict):
        return
    for key in _MAPS:
        for name, child in schema.get(key, {}).items():
            yield from _nodes(child, path + (key, name))
    for key in _SINGLE:
        if key in schema:
            yield from _nodes(schema[key], path + (key,))
    for key in _ARRAYS:
        for index, child in enumerate(schema.get(key, [])):
            yield from _nodes(child, path + (key, index))


def check_schema(schema, origin='<schema>'):
    """Return a valid schema; reject unsupported dialects and nonlocal references."""
    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError
    except ImportError as exc:
        raise ValueError(f'{origin}: install runtime dependencies with '
                         'python3 -m pip install -r requirements.txt') from exc
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f'{origin}{_where(exc.absolute_path)}: invalid JSON Schema: {exc.message}') from exc
    nodes = dict(_nodes(schema))
    anchors = {}
    for path, node in nodes.items():
        if not isinstance(node, dict):
            continue
        if node.get('$schema', DRAFT) != DRAFT:
            raise ValueError(f'{origin}{_where(path)}: unsupported schema dialect')
        if path and '$id' in node:
            raise ValueError(f'{origin}{_where(path)}: nested $id resources are not supported')
        for key in ('$anchor', '$dynamicAnchor'):
            if key in node:
                anchor = node[key]
                if anchor in anchors and anchors[anchor] != path:
                    raise ValueError(f'{origin}{_where(path)}: duplicate anchor {anchor!r}')
                anchors[anchor] = path
    for path, node in nodes.items():
        if not isinstance(node, dict):
            continue
        for key in ('$ref', '$dynamicRef'):
            if key not in node:
                continue
            ref = node[key]
            label = f'{origin}{_where(path + (key,))}'
            if not ref.startswith('#'):
                raise ValueError(f'{label}: external reference is not allowed: {ref!r}')
            fragment = unquote(ref[1:])
            if not fragment:
                target_path = ()
            elif fragment.startswith('/'):
                target_path = tuple(fragment[1:].split('/'))
                if any(re.search(r'~(?:[^01]|$)', p) for p in target_path):
                    raise ValueError(f'{label}: invalid JSON Pointer escape: {ref!r}')
                target_path = tuple(p.replace('~1', '/').replace('~0', '~') for p in target_path)
                target_path = next((p for p in nodes if tuple(map(str, p)) == target_path), None)
            else:
                target_path = anchors.get(fragment)
            if target_path not in nodes:
                raise ValueError(f'{label}: unresolved local schema reference: {ref!r}')
    return schema


def parse_schema(data, origin='<schema>'):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate JSON key {key!r}')
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f'non-JSON numeric constant {value}')
    try:
        text = data.decode('utf-8') if isinstance(data, bytes) else data
        schema = json.loads(text, object_pairs_hook=unique, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise SchemaDecodeError(f'{origin}: not valid JSON/UTF-8 ({exc})') from exc
    try:
        return check_schema(schema, origin)
    except RecursionError as exc:
        raise ValueError(f'{origin}: schema nesting is too deep') from exc


def load_schema(path):
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise ValueError(f'{path}: cannot read schema ({exc})') from exc
    return parse_schema(data, str(path))


def bundled_schema_problems(directory=None):
    """Always check every required bundled asset; never silently skip missing files."""
    problems = []
    directory = Path(directory) if directory is not None else SCHEMA_DIR
    for name in SCHEMA_NAMES:
        try:
            load_schema(directory / (name + '.json'))
        except ValueError as exc:
            problems.append(str(exc))
    return problems
