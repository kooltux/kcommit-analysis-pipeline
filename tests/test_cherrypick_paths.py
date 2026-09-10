"""Tests for the direct per-revision cherry-pick cache path helpers."""

import os

from lib.cherrypick_paths import (
    _safe_revision_filename,
    delete_db,
    ensure_cache_dir,
    get_cherry_db_path,
    load_or_create_db,
)
from lib.cherrypick_db import CherryDB


def test_safe_revision_filename_passes_through_plain_revisions():
    """Ordinary tag-like revisions are returned unchanged."""
    assert _safe_revision_filename('v6.1.1') == 'v6.1.1'


def test_safe_revision_filename_normalizes_separators():
    """Forward and backward slashes both collapse to a single underscore."""
    assert _safe_revision_filename('origin/stable/linux-6.1.y') == 'origin_stable_linux-6.1.y'
    assert _safe_revision_filename(r'origin\stable\linux-6.1.y') == 'origin_stable_linux-6.1.y'


def test_get_cherry_db_path_is_direct_file(tmp_path):
    """The target revision names a file directly inside the cache directory."""
    assert get_cherry_db_path(str(tmp_path), 'v6.1.1') == str(tmp_path / 'v6.1.1')


def test_get_cherry_db_path_normalizes_ref_separators(tmp_path):
    """Slash-containing Git refs still map to one direct database file."""
    expected = str(tmp_path / 'origin_stable_linux-6.1.y')
    assert get_cherry_db_path(str(tmp_path), 'origin/stable/linux-6.1.y') == expected
    assert get_cherry_db_path(str(tmp_path), r'origin\stable\linux-6.1.y') == expected


def test_ensure_cache_dir_creates_only_base_directory(tmp_path):
    """ensure_cache_dir() creates cache_dir itself, not a per-revision subdirectory."""
    cache_dir = tmp_path / 'cache'
    result = ensure_cache_dir(str(cache_dir), 'v6.1.1')

    assert result == str(cache_dir)
    assert cache_dir.is_dir()
    assert not (cache_dir / 'v6.1.1').exists()


def test_ensure_cache_dir_rev_old_is_optional(tmp_path):
    """rev_old is accepted for backward compatibility but not required."""
    cache_dir = tmp_path / 'cache2'
    result = ensure_cache_dir(str(cache_dir))

    assert result == str(cache_dir)
    assert cache_dir.is_dir()


def test_load_or_create_db_creates_direct_file_and_base_dir(tmp_path):
    """Only the configured cache directory is created; revision is the DB file."""
    cache_dir = tmp_path / 'cache'
    db = load_or_create_db(str(cache_dir), 'v6.1')
    assert isinstance(db, CherryDB)
    db.save()

    assert cache_dir.is_dir()
    assert (cache_dir / 'v6.1').is_file()
    assert not (cache_dir / 'v6.1' / 'cherry.db').exists()


def test_delete_db_removes_direct_revision_file(tmp_path):
    """delete_db() removes the direct revision-named database file."""
    cache_dir = tmp_path / 'cache'
    db = load_or_create_db(str(cache_dir), 'v6.1')
    db.save()

    assert delete_db(str(cache_dir), 'v6.1') is True
    assert not (cache_dir / 'v6.1').exists()
    assert delete_db(str(cache_dir), 'v6.1') is False


def test_delete_db_noop_when_cache_dir_missing(tmp_path):
    """delete_db() is a safe no-op when the cache directory was never created."""
    cache_dir = tmp_path / 'never-created'
    assert delete_db(str(cache_dir), 'v6.1') is False
