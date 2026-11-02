"""Assembly and upload use the real portable server."""
import json

from lib.ai_contract import encode
from test_ai_package_server import app, package, snapshots, workflow
from test_ai_server_runtime import request, running


def test_assembly_returns_valid_result_without_storage(app, workflow):
    name, documents = workflow
    inputs = {role: documents[role] for role in ('analyst', 'cve', 'reviewer')}
    with running(app) as (port, log, errors):
        status, headers, body = request(port, '/assemble/' + name,
                                       method='POST', body=encode(inputs))
        assert status == 200, body
        assert json.loads(body) == documents['result']
        assert request(port, '/result/' + name)[0] == 404
        assert request(port, '/result/' + name, method='POST', body=body)[0] == 200


def test_assembly_rejects_invalid_inputs(app, workflow):
    name, documents = workflow
    with running(app) as (port, log, errors):
        for value in ({}, documents):
            status, headers, body = request(port, '/assemble/' + name,
                                           method='POST', body=encode(value))
            assert status == 400, body
        assert request(port, '/assemble/batch_999/999.json', method='POST', body=b'{}')[0] == 404
        assert request(port, '/result/' + name)[0] == 404
