"""Batch detail returns paired URLs without legacy parallel arrays."""
from test_ai_server_runtime import app, namespace
from test_ai_server_pagination import listings
from test_ai_server_api import invoke


def test_batch_pairs_match_source_names_and_preserve_metadata(listings):
    batch = listings['BATCHES']['batch_002']
    full = invoke(listings, '/batch/batch_002')
    assert full == dict(batch, run_id=listings['MANIFEST']['run_id'], chunks=[
        {'chunk': '/chunk/' + name, 'result': '/result/' + name} for name in batch['chunks']])
    assert 'results' not in full
    assert all(isinstance(name, str) for name in batch['chunks'])


def test_empty_batch_returns_empty_pairs(listings, monkeypatch):
    batch = {'batch_id': 'empty', 'batch_number': 4, 'total_commits': 0, 'chunks': []}
    monkeypatch.setitem(listings['BATCHES'], 'empty', batch)
    assert invoke(listings, '/batch/empty?limit=1&offset=999') == dict(
        batch, run_id=listings['MANIFEST']['run_id'])
