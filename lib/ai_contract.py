"""AI chunk and result contracts shared by the pipeline, server and importer."""
import hashlib
import json
import re

SHA = re.compile(r'^[0-9a-f]{40}$')
NAME = re.compile(r'^[0-9]+\.json$')
FIELDS = ('commit', 'subject', 'author_name', 'author_email', 'author_org',
          'author_time', 'body', 'files', 'stats', 'meta', 'product_evidence')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                       ensure_ascii=False) + '\n').encode('utf-8')

def input_schema():
    """Generate the input JSON Schema from the same field list as project_commit."""
    def string(description):
        return {'type': 'string', 'description': description}
    def count(description):
        return {'type': 'integer', 'minimum': 0, 'description': description}
    fields = {key: string(key.replace('_', ' ') + ' from the source commit.')
              for key in FIELDS if key not in ('author_time', 'files', 'stats', 'meta', 'product_evidence')}
    fields['commit']['pattern'] = SHA.pattern
    fields.update({
        'author_time': {'type': 'integer', 'description': 'Unix author timestamp in seconds.'},
        'files': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Changed source paths.'},
        'stats': {'type': 'object', 'additionalProperties': True, 'description': 'Source size indicators.'},
        'meta': {'type': 'object', 'additionalProperties': True, 'description': 'Message annotation flags.'},
        'product_evidence': {'type': 'array', 'items': {'type': 'string'},
                             'description': 'Product relevance evidence tags.'},
    })
    props = {
        'schema_version': string('AI exchange contract version.'),
        'pipeline_version': string('Version of the pipeline that generated this input.'),
        'run_id': string('SHA-256 identity of the source data and effective contracts.'),
        'source_chunk': string('Basename of this numbered source chunk.'),
        'input_schema_checksum': string('SHA-256 checksum of the input schema bytes.'),
        'output_schema_checksum': string('SHA-256 checksum of the output schema bytes.'),
        'total_commits': count('Number of commits in this chunk.'),
        'chunk_info': {'type': 'object', 'description': 'Position in the complete source set.',
                       'properties': {
                           'chunk_number': count('One-based chunk number.'),
                           'total_chunks': count('Number of chunks in the bundle.'),
                           'start_index': count('Zero-based inclusive first index.'),
                           'end_index': count('Zero-based exclusive last index.')},
                       'required': ['chunk_number', 'total_chunks', 'start_index', 'end_index'],
                       'additionalProperties': False},
        'commits': {'type': 'array', 'description': 'Commit records selected by prefilter.',
                    'items': {'type': 'object', 'properties': fields,
                              'required': list(FIELDS), 'additionalProperties': False}},
    }
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            'title': 'AI analysis source chunk', 'type': 'object',
            'properties': props, 'required': list(props), 'additionalProperties': False}

def project_commit(commit, product_map):
    from lib.scoring import _collect_product_evidence
    data = {key: commit.get(key, '') for key in FIELDS}
    data['author_time'] = commit.get('author_time', 0)
    data['files'] = list(commit.get('files') or [])
    data['stats'] = commit.get('stats') or {}
    data['meta'] = commit.get('meta') or {}
    data['product_evidence'] = (_collect_product_evidence(commit, product_map)
                                if product_map else [])
    return data

def validate_chunk(chunk, schema_checksum, output_checksum, run_id, name):
    if not NAME.fullmatch(name):
        raise ValueError('Invalid chunk filename')
    if not isinstance(chunk, dict) or set(chunk) != set(input_schema()['required']):
        raise ValueError('Invalid chunk envelope')
    for key, value in (('schema_version', '1.0'), ('run_id', run_id),
                       ('source_chunk', name), ('input_schema_checksum', schema_checksum),
                       ('output_schema_checksum', output_checksum)):
        if chunk[key] != value:
            raise ValueError('Chunk identity mismatch: ' + key)
    commits = chunk['commits']
    info = chunk['chunk_info']
    if (not isinstance(chunk['pipeline_version'], str) or not isinstance(commits, list)
            or type(chunk['total_commits']) is not int or chunk['total_commits'] != len(commits)
            or not isinstance(info, dict) or set(info) != {'chunk_number', 'total_chunks', 'start_index', 'end_index'}
            or any(type(info[key]) is not int for key in info)
            or info['chunk_number'] < 1 or info['total_chunks'] < info['chunk_number']
            or info['start_index'] < 0 or info['end_index'] - info['start_index'] != len(commits)):
        raise ValueError('Invalid chunk structure or counts')
    for item in commits:
        if (not isinstance(item, dict) or set(item) != set(FIELDS)
                or not isinstance(item['commit'], str) or not SHA.fullmatch(item['commit'])
                or any(not isinstance(item[key], str) for key in
                       ('subject', 'author_name', 'author_email', 'author_org', 'body'))
                or type(item['author_time']) is not int
                or not isinstance(item['files'], list)
                or any(not isinstance(path, str) for path in item['files'])
                or not isinstance(item['stats'], dict) or not isinstance(item['meta'], dict)
                or not isinstance(item['product_evidence'], list)
                or any(not isinstance(tag, str) for tag in item['product_evidence'])):
            raise ValueError('Invalid source commit')
    if len({item['commit'] for item in commits}) != len(commits):
        raise ValueError('Duplicate source commit')
    return True

def validate_result(result, chunk, schema, input_checksum):
    """Validate identity, completeness, and every field of every result."""
    if not isinstance(result, dict) or set(result) != set(schema['required']):
        raise ValueError('Invalid result envelope')
    expected = {'schema_version': '1.0', 'run_id': chunk['run_id'],
                'source_chunk': chunk['source_chunk'], 'input_checksum': input_checksum,
                'input_schema_checksum': chunk['input_schema_checksum'],
                'output_schema_checksum': chunk['output_schema_checksum']}
    if any(result.get(key) != value for key, value in expected.items()):
        raise ValueError('Result identity mismatch')
    if type(result['total_commits']) is not int or result['total_commits'] != chunk['total_commits']:
        raise ValueError('Result source count mismatch')
    if result['analysis_status'] not in ('complete', 'partial'):
        raise ValueError('Invalid analysis status')
    results = result['results']
    if not isinstance(results, dict):
        raise ValueError('Results must be keyed by full commit SHA')
    source = {item['commit'] for item in chunk['commits']}
    if not set(results).issubset(source):
        raise ValueError('Result contains an unknown SHA')
    if type(result['analyzed_commits']) is not int or result['analyzed_commits'] != len(results):
        raise ValueError('Analyzed count mismatch')
    if result['analysis_status'] == 'complete' and set(results) != source:
        raise ValueError('Incomplete result marked complete')
    props = schema['properties']['results']['additionalProperties']['properties']
    for item in results.values():
        if not isinstance(item, dict) or set(item) != set(props):
            raise ValueError('Invalid per-commit result fields')
        for key, spec in props.items():
            value = item[key]
            kind = spec['type']
            if kind == 'boolean' and type(value) is not bool:
                raise ValueError('Invalid boolean: ' + key)
            if kind == 'string' and (not isinstance(value, str)
                                     or ('enum' in spec and value not in spec['enum'])):
                raise ValueError('Invalid string: ' + key)
            if kind == 'array':
                item_spec = spec['items']
                if (not isinstance(value, list) or any(
                        (type(v) is not int if item_spec['type'] == 'integer' else not isinstance(v, str))
                        or ('enum' in item_spec and v not in item_spec['enum'])
                        or ('minimum' in item_spec and v < item_spec['minimum'])
                        or ('maximum' in item_spec and v > item_spec['maximum'])
                        or ('pattern' in item_spec and not re.fullmatch(item_spec['pattern'], v))
                        for v in value)):
                    raise ValueError('Invalid array: ' + key)
        risks = item.get('ai_risks_if_not_backported')
        if risks is not None and (len(risks) != len(set(risks))
                                  or ('none' in risks and len(risks) != 1)):
            raise ValueError('Invalid risk combination')
        ids = item.get('ai_cve_ids')
        probabilities = item.get('ai_cve_probabilities')
        if ids is not None and probabilities is not None and len(ids) != len(probabilities):
            raise ValueError('CVE ID and probability counts differ')
    if len(results) > result['total_commits']:
        raise ValueError('Too many results')
    return True
