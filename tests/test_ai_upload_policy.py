"""Canonical validation precedes publication; acknowledgements follow publication."""
import importlib
import json
import threading
from pathlib import Path
import pytest
from test_ai_server_runtime import app, namespace

@pytest.mark.parametrize('failure', [None, ValueError, OSError])
def test_publication_precedes_receipt_and_failures_do_not_acknowledge(namespace, monkeypatch, failure):
    module = importlib.import_module(namespace['__package__'] + '.versioned_routes')
    sha = 'a' * 40
    events = []
    responses = []
    record = {'selected': 'record'}

    def assemble(*args):
        events.append('validate')
        return {sha: record}

    class Store:
        _lock = threading.RLock()

        def put_many(self, records):
            assert records == {sha: record} and events == ['validate']
            events.append('publish')
            if failure:
                raise failure('publication failed')
            return {sha: 'f' * 64}
    monkeypatch.setattr(module, 'assemble_contributions', assemble)
    monkeypatch.setattr(module, 'STORE', Store())
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.path = '/v1/result'
    handler.read_json = lambda: (b'{}', {})

    def reply(raw):
        assert events == ['validate', 'publish']
        responses.append(json.loads(raw))
    handler.send_bytes = reply
    if failure:
        with pytest.raises(failure, match='publication failed'):
            module.contributions(handler)
        assert responses == []
    else:
        module.contributions(handler)
        assert responses == [dict(status='stored', run_id=module.RUN_ID, results={sha: 'f' * 64})]
    assert not Path(namespace['RESULTS']).exists()

@pytest.mark.parametrize('endpoint', ['/v1/result', '/v2/validate/workflow'])
def test_failed_gate_never_reaches_store(namespace, monkeypatch, endpoint):
    module = importlib.import_module(namespace['__package__'] + '.versioned_routes')

    def reject(*args):
        raise ValueError('invalid contributions')

    class Forbidden:

        def __getattr__(self, name):
            pytest.fail('storage reached before validation')
    monkeypatch.setattr(module, 'assemble_contributions', reject)
    monkeypatch.setattr(module, 'STORE', Forbidden())
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.path = endpoint
    handler.read_json = lambda: (b'{}', {})
    errors = []
    handler.send_error = lambda code, message: errors.append((code, str(message)))
    module.contributions(handler)
    assert errors == [(400, 'invalid contributions')]
    assert not Path(namespace['RESULTS']).exists()
