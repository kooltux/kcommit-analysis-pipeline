"""Upload preparation precedes storage; acknowledgements follow atomic replacement."""
import json
from pathlib import Path

import pytest

from test_ai_server_runtime import app, namespace


def test_default_upload_policy_preserves_exact_bytes(namespace, monkeypatch):
    name = next(iter(namespace['NAMES']))
    raw = b'{ "results": {} }\n'
    document = json.loads(raw)
    validated = []
    monkeypatch.setitem(namespace, 'validate', lambda *args: validated.append(args))
    stored, receipt = namespace['prepare_upload'](name, raw, document)
    assert validated == [(name, document)]
    assert stored is raw
    assert receipt == {'status': 'ok'}
    assert not Path(namespace['RESULTS']).exists()


def test_default_upload_policy_propagates_validation_failure(namespace, monkeypatch):
    def reject(name, document):
        raise ValueError('rejected before storage')
    monkeypatch.setitem(namespace, 'validate', reject)
    with pytest.raises(ValueError, match='rejected before storage'):
        namespace['prepare_upload'](next(iter(namespace['NAMES'])), b'{}', {})
    assert not Path(namespace['RESULTS']).exists()


def test_handler_publishes_before_receipt_and_checksums_published_bytes(namespace, monkeypatch):
    name = next(iter(namespace['NAMES']))
    prepared = b'{ "results": {} }\n'
    published = b'{"results":{}}\n'
    prepared_checksum = namespace['checksum'](prepared)
    receipt = {'status': 'stored', 'result_checksum': prepared_checksum}
    events, observed = [], []
    def prepare(actual_name, raw, document):
        assert (actual_name, raw, document) == (name, b'{}', {})
        assert events == []
        events.append('prepare')
        return prepared, receipt
    class Store:
        def write_chunk(self, actual_name, document):
            assert actual_name == name and document == json.loads(prepared)
            assert events == ['prepare']
            events.append('publish')
            return published
    def respond(raw):
        assert events == ['prepare', 'publish']
        events.append('respond')
        observed.append(json.loads(raw))
    monkeypatch.setitem(namespace, 'prepare_upload', prepare)
    monkeypatch.setitem(namespace, 'RESULT_STORE', Store())
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.read_json = lambda: (b'{}', {})
    handler.send_bytes = respond
    handler.post_result(name)
    assert events == ['prepare', 'publish', 'respond']
    assert observed == [{'status': 'stored', 'result_checksum': namespace['checksum'](published)}]
    assert observed[0]['result_checksum'] != prepared_checksum
    assert not Path(namespace['RESULTS']).exists()


@pytest.mark.parametrize('failure', [OSError, ValueError])
def test_handler_propagates_publication_failure_without_receipt(namespace, monkeypatch, failure):
    name = next(iter(namespace['NAMES']))
    prepared = b'{"results":{}}\n'
    calls, responses = [], []
    class Store:
        def write_chunk(self, actual_name, document):
            calls.append((actual_name, document))
            raise failure('publication failed')
    monkeypatch.setitem(namespace, 'prepare_upload',
                        lambda *args: (prepared, {'status': 'stored'}))
    monkeypatch.setitem(namespace, 'RESULT_STORE', Store())
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.read_json = lambda: (b'{}', {})
    handler.send_bytes = lambda raw: responses.append(('success', raw))
    handler.send_error = lambda *args: responses.append(('error', args))
    with pytest.raises(failure, match='publication failed'):
        handler.post_result(name)
    assert calls == [(name, json.loads(prepared))]
    assert responses == []
    assert not Path(namespace['RESULTS']).exists()


def test_handler_does_not_create_storage_when_preparation_fails(namespace, monkeypatch):
    def reject(*args):
        raise ValueError('invalid contributions')
    monkeypatch.setitem(namespace, 'prepare_upload', reject)
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.read_json = lambda: (b'{}', {})
    errors = []
    handler.send_error = lambda code, error: errors.append((code, str(error)))
    handler.post_result(next(iter(namespace['NAMES'])))
    assert errors == [(400, 'invalid contributions')]
    assert not Path(namespace['RESULTS']).exists()
