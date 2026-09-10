"""Tests for SQLite variable-limit handling in CherryDB lookups."""

import lib.cherrypick_db as cherrypick_db
from lib.cherrypick_db import CherryDB


def _result(ok=True, conflicts=None, error=None):
    return {
        'ok': ok,
        'conflicts': conflicts or [],
        'error': error,
    }


def test_get_results_chunks_large_lookup(tmp_path, monkeypatch):
    """Results from SQLite lookup chunks are merged into one mapping."""
    monkeypatch.setattr(cherrypick_db, '_RESULT_LOOKUP_CHUNK_SIZE', 3)
    db = CherryDB(str(tmp_path / 'cherry.db'))
    try:
        shas = ['%040x' % index for index in range(7)]
        db.add_results({
            sha: _result(ok=index % 2 == 0,
                         conflicts=['x.c'] if index % 2 else [])
            for index, sha in enumerate(shas)
        })

        results = db.get_results(shas)

        assert set(results) == set(shas)
        assert results[shas[0]]['ok'] is True
        assert results[shas[1]]['ok'] is False
        assert results[shas[1]]['conflicts'] == ['x.c']
    finally:
        db.save()


def test_get_results_ignores_unknown_and_duplicate_shas(tmp_path, monkeypatch):
    """Stable deduplication avoids redundant bindings and ignores unknown SHAs."""
    monkeypatch.setattr(cherrypick_db, '_RESULT_LOOKUP_CHUNK_SIZE', 2)
    db = CherryDB(str(tmp_path / 'cherry.db'))
    try:
        sha1 = 'a' * 40
        sha2 = 'b' * 40
        unknown = 'c' * 40
        db.add_results({
            sha1: _result(),
            sha2: _result(ok=False, error='conflict'),
        })

        results = db.get_results([sha1, sha2, sha1, unknown, sha2])

        assert set(results) == {sha1, sha2}
        assert results[sha1]['ok'] is True
        assert results[sha2]['ok'] is False
        assert results[sha2]['error'] == 'conflict'
    finally:
        db.save()
