"""Tests for CherryDB SQLite result storage and chunked lookups."""

from lib.cherrypick_db import CherryDB
import lib.cherrypick_db as cherrypick_db


def _result(ok=True, conflicts=None, error=None):
    return {
        'ok': ok,
        'conflicts': conflicts or [],
        'error': error,
    }


def test_add_and_get_single_result(tmp_path):
    """A single stored result round-trips through get_results()."""
    db = CherryDB(str(tmp_path / 'cherry.db'))
    try:
        db.add_result('a' * 40, _result(ok=True, conflicts=['x.c']))
        results = db.get_results(['a' * 40])
        assert results['a' * 40]['ok'] is True
        assert results['a' * 40]['conflicts'] == ['x.c']
    finally:
        db.save()


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


def test_get_results_empty_input_returns_empty_dict(tmp_path):
    """get_results() short-circuits on empty/None input without querying."""
    db = CherryDB(str(tmp_path / 'cherry.db'))
    try:
        assert db.get_results([]) == {}
        assert db.get_results(None) == {}
    finally:
        db.save()


def test_count_and_get_all_shas(tmp_path):
    """count() and get_all_shas() reflect stored rows."""
    db = CherryDB(str(tmp_path / 'cherry.db'))
    try:
        db.add_results({'a' * 40: _result(), 'b' * 40: _result(ok=False)})
        assert db.count() == 2
        assert db.get_all_shas() == {'a' * 40, 'b' * 40}
    finally:
        db.save()


def test_cherrydb_reexports_path_helpers_for_backward_compatibility(tmp_path):
    """lib.cherrypick_db still exposes the path helpers after the v19.9.0 split."""
    cache_dir = tmp_path / 'cache'
    db = cherrypick_db.load_or_create_db(str(cache_dir), 'v6.1')
    db.save()

    assert cherrypick_db.get_cherry_db_path(str(cache_dir), 'v6.1') == str(cache_dir / 'v6.1')
    assert cherrypick_db.delete_db(str(cache_dir), 'v6.1') is True
