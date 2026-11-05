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


def test_handler_stores_prepared_bytes_before_sending_receipt(namespace, monkeypatch):
    name = next(iter(namespace['NAMES']))
    stored = Path(namespace['RESULTS']) / name
    prepared = b'prepared result bytes\n'
    receipt = {'status': 'stored', 'result_checksum': namespace['checksum'](prepared)}
    observed = []
    def prepare(actual_name, raw, document):
        assert (actual_name, raw, document) == (name, b'{}', {})
        assert not stored.exists()
        return prepared, receipt
    def respond(raw):
        assert stored.read_bytes() == prepared
        observed.append(json.loads(raw))
    monkeypatch.setitem(namespace, 'prepare_upload', prepare)
    handler = namespace['Handler'].__new__(namespace['Handler'])
    handler.read_json = lambda: (b'{}', {})
    handler.send_bytes = respond
    handler.post_result(name)
    assert observed == [receipt]
    assert not list(stored.parent.glob('.upload-*'))


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
