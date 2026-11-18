"""Packaged v1 source URLs resolve to the canonical analysis input contract."""
import json
import pytest
from jsonschema import Draft202012Validator
from test_ai_package_server import app, package, snapshots
from test_ai_server_runtime import basic, request, running

@pytest.mark.parametrize('auth', [None, 'reviewer:secret'])
def test_packaged_entries_resolve_selected_sources(app, package, auth):
    with running(app, auth=auth) as (port, log, errors):
        token = basic(auth) if auth else None
        listing = json.loads(request(port, '/v1/chunks', authorization=token)[2])
        schema = json.loads(request(port, '/v1/schema/input', authorization=token)[2])
        assert listing['run_id'] == package['manifest']['analysis_id']
        assert [x['name'] for x in listing['chunks']] == sorted(package['manifest']['chunks'])
        for entry in listing['chunks']:
            assert set(entry) == {'name', 'url'} and entry['url'] == '/v1/chunk/' + entry['name']
            status, _, raw = request(port, entry['url'], authorization=token)
            assert status == 200
            source = json.loads(raw)
            Draft202012Validator(schema).validate(source)
            archived = json.loads(package['files']['ai_analysis_input/' + entry['name']])
            assert source == dict(run_id=listing['run_id'], commits=archived['commits'])
        for name in ('batch_999/999.json', '../001.json', 'batch_001/../001.json'):
            assert request(port, '/v1/chunk/' + name, authorization=token)[0] == 404
