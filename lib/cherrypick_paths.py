"""Direct per-revision cherry-pick cache path helpers.

v19.9.0:
  Split out of lib/cherrypick_db.py. The cherry-pick cache layout changed
  from a per-revision subdirectory (``<cache_dir>/<rev_old>/cherry.db``) to
  a single direct file named after the target revision
  (``<cache_dir>/<safe-rev_old>``). Git revision names may contain forward
  slashes (e.g. ``origin/stable/linux-6.1.y``); on platforms where a
  backslash is also a path separator, both characters are normalized to
  ``_`` so the cache directory never gains unexpected nested directories.

  ensure_cache_dir() now only creates the single shared cache_dir --
  callers no longer get one subdirectory per revision.

  delete_db() was moved here from lib/cherrypick_db.py so all cache-layout
  logic (path construction, directory creation, deletion) lives in one
  module. lib/cherrypick_db.py re-exports all five functions so existing
  ``from lib.cherrypick_db import ...`` call sites keep working unchanged.
"""
import os


def _safe_revision_filename(revision):
    """Return a filesystem-safe direct filename for a Git revision.

    Normal revision names (for example ``v6.1.1``) are unchanged. Git refs
    may contain forward slashes and callers may run on platforms where a
    backslash is also a path separator; both are normalized to ``_`` so the
    database remains a single file directly inside the configured cache
    directory rather than creating nested subdirectories.
    """
    return str(revision).replace('/', '_').replace('\\', '_')


def get_cherry_db_path(cache_dir, rev_old):
    """Return the direct per-revision cherry-pick database path.

    The canonical layout is ``<cache_dir>/<safe-rev_old>`` -- a single file
    directly inside ``cache_dir``. No revision subdirectory or generic
    ``cherry.db`` filename is used.

    Args:
        cache_dir: base cache directory (e.g., '/path/to/cherry-cache')
        rev_old: target revision (e.g., 'v6.1.1')

    Returns:
        full path to the direct per-revision database file
    """
    return os.path.join(cache_dir, _safe_revision_filename(rev_old))


def ensure_cache_dir(cache_dir, rev_old=None):
    """Ensure the configured cherry-pick cache base directory exists.

    ``rev_old`` is accepted (and ignored) for backward-compatible callers;
    revision-specific databases are direct files inside ``cache_dir``, so no
    per-revision subdirectory is created.

    Args:
        cache_dir: base cache directory
        rev_old: unused; kept for backward compatibility

    Returns:
        cache_dir, unchanged
    """
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def load_or_create_db(cache_dir, rev_old):
    """Load existing database or create a new one at the direct file path.

    Args:
        cache_dir: base cache directory
        rev_old: target revision

    Returns:
        CherryDB instance
    """
    from lib.cherrypick_db import CherryDB
    ensure_cache_dir(cache_dir)
    return CherryDB(get_cherry_db_path(cache_dir, rev_old))


def delete_db(cache_dir, rev_old):
    """Delete the cherry-pick database file for a target revision, if present.

    Used by the ``cp-check --force`` command to clear cached results and
    restart testing from scratch. Silently no-ops if the file does not exist.

    Args:
        cache_dir: base cache directory
        rev_old: target revision

    Returns:
        True if a database file was removed, False if none existed.
    """
    db_path = get_cherry_db_path(cache_dir, rev_old)
    if os.path.exists(db_path):
        os.remove(db_path)
        return True
    return False
