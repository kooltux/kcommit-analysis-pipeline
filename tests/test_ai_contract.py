"""Unit tests for the AI input and result exchange contract."""
import copy

import pytest

from lib.ai_contract import digest, encode, input_schema, project_commit, validate_chunk, validate_result

SHA = 'a' * 40


def fixtures():
    schema = input_schema()
    commit = project_commit({'commit': SHA, 'subject': 'fix', 'files': ['net/core.c'],
                             'author_time': 1700000000}, {})
    chunk = {'schema_version': '1.0', 'pipeline_version': 'v19.9.1',
             'run_id': 'r' * 64, 'source_chunk': '1.json',
             'input_schema_checksum': digest(encode(schema)),
             'output_schema_checksum': 'b' * 64, 'total_commits': 1,
             'chunk_info': {'chunk_number': 1, 'total_chunks': 1,
                            'start_index': 0, 'end_index': 1}, 'commits': [commit]}
    return schema, chunk


def test_schema_matches_projected_commit_fields():
    schema, chunk = fixtures()
    assert set(schema['properties']['commits']['items']['required']) == set(chunk['commits'][0])
    assert 'score' not in chunk['commits'][0]
    assert 'cherry_pickable' not in chunk['commits'][0]


def test_chunk_identity_and_coverage():
    schema, chunk = fixtures()
    assert validate_chunk(chunk, chunk['input_schema_checksum'], 'b' * 64, 'r' * 64, '1.json')
    bad = copy.deepcopy(chunk)
    bad['source_chunk'] = '2.json'
    with pytest.raises(ValueError, match='identity'):
        validate_chunk(bad, chunk['input_schema_checksum'], 'b' * 64, 'r' * 64, '1.json')
    with pytest.raises(ValueError, match='filename'):
        validate_chunk(chunk, chunk['input_schema_checksum'], 'b' * 64, 'r' * 64, '../1.json')


def test_chunk_duplicate_sha_rejected():
    _, chunk = fixtures()
    chunk['commits'].append(dict(chunk['commits'][0]))
    chunk['total_commits'] = 2
    chunk['chunk_info']['end_index'] = 2
    with pytest.raises(ValueError, match='Duplicate'):
        validate_chunk(chunk, chunk['input_schema_checksum'], 'b' * 64, 'r' * 64, '1.json')


def test_result_validates_identity_and_complete_coverage():
    _, chunk = fixtures()
    record = {'ai_is_security_fix': True, 'ai_risks_if_not_backported': ['security_vulnerability']}
    schema = {'required': ['schema_version', 'run_id', 'source_chunk', 'input_checksum',
                           'input_schema_checksum', 'output_schema_checksum', 'total_commits',
                           'analyzed_commits', 'analysis_status', 'results'],
              'properties': {'results': {'additionalProperties': {'properties': {
                  'ai_is_security_fix': {'type': 'boolean'},
                  'ai_risks_if_not_backported': {'type': 'array', 'items': {
                      'type': 'string', 'enum': ['security_vulnerability', 'none']}}}}}}}
    result = {'schema_version': '1.0', 'run_id': chunk['run_id'],
              'source_chunk': chunk['source_chunk'], 'input_checksum': 'c' * 64,
              'input_schema_checksum': chunk['input_schema_checksum'],
              'output_schema_checksum': chunk['output_schema_checksum'],
              'total_commits': 1, 'analyzed_commits': 1,
              'analysis_status': 'complete', 'results': {SHA: record}}
    assert validate_result(result, chunk, schema, 'c' * 64)
    bad = copy.deepcopy(result)
    bad['input_checksum'] = 'd' * 64
    with pytest.raises(ValueError, match='identity'):
        validate_result(bad, chunk, schema, 'c' * 64)
    bad = copy.deepcopy(result)
    bad['results'] = {}
    bad['analyzed_commits'] = 0
    with pytest.raises(ValueError, match='Incomplete'):
        validate_result(bad, chunk, schema, 'c' * 64)
    bad = copy.deepcopy(result)
    bad['results'][SHA]['ai_risks_if_not_backported'] = ['unrecognized']
    with pytest.raises(ValueError, match='array'):
        validate_result(bad, chunk, schema, 'c' * 64)
