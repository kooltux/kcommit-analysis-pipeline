"""Batch entries expose canonical names usable directly for combined context."""
import json

import pytest
from jsonschema import Draft202012Validator

from test_ai_package_server import app, package, snapshots
from test_ai_server_runtime import basic, request, running


@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
@pytest.mark.parametrize('query,offset,limit', [('', 0, None),
    ('?limit=1&offset=1', 1, 1), ('?offset=999', 999, None)])
def test_batch_entry_names_resolve_context_and_paths(app, package, auth, query, offset, limit):
    manifest = package['manifest']
    batch = manifest['batches'][0]
    stop = offset + limit if limit is not None else None
    expected = batch['chunks'][offset:stop]
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        endpoint = '/batch/' + batch['batch_id'] + query
        if auth:
            assert request(port, endpoint)[0] == 401
        status, _, raw = request(port, endpoint, authorization=token)
        assert status == 200
        detail = json.loads(raw)
        assert detail['run_id'] == manifest['run_id']
        assert detail['total_commits'] == batch['total_commits']
        assert detail['batch_number'] == batch['batch_number']
        assert [entry['name'] for entry in detail['chunks']] == expected
        if offset == 1:
            assert expected == ['batch_001/002.json']
        catalog = json.loads(request(port, '/api', authorization=token)[2])
        schema = catalog['response_schemas']['batch']
        Draft202012Validator(schema).validate(detail)
        item_schema = schema['properties']['chunks']['items']
        assert set(item_schema['required']) == {'name', 'path', 'result_path'}
        assert item_schema['additionalProperties'] is False
        sample_name = batch['chunks'][0]
        sample = dict(name=sample_name, path='/chunk/' + sample_name, result_path='/result/' + sample_name)
        item_validator = Draft202012Validator(item_schema)
        item_validator.validate(sample)
        assert not item_validator.is_valid(dict(sample, name=sample['path']))
        assert not item_validator.is_valid(dict(chunk=sample['path'], result=sample['result_path']))
        for entry in detail['chunks']:
            assert set(entry) == {'name', 'path', 'result_path'}
            assert entry['path'] == '/chunk/' + entry['name']
            assert entry['result_path'] == '/result/' + entry['name']
            code, _, context_raw = request(port, '/context/' + entry['name'], authorization=token)
            assert code == 200
            context = json.loads(context_raw)
            assert context['envelope']['source_chunk'] == entry['name']
            assert context['chunk']['source_chunk'] == entry['name']
            source = package['files']['ai_analysis_input/' + entry['name']]
            source_response = request(port, entry['path'], authorization=token)
            assert source_response[0] == 200 and source_response[2] == source
            assert request(port, entry['result_path'], authorization=token)[0] == 404
        listing = json.loads(request(port, '/chunks', authorization=token)[2])
        assert listing['chunks'] == ['/chunk/' + name for name in manifest['chunks']]
        batches = json.loads(request(port, '/batches', authorization=token)[2])
        assert batches['batches'][0]['chunks'] == batch['chunks']
