"""Cherry-pick cache database for kcommit-analysis-pipeline.

Stores cherry-pick test results in SQLite for efficient incremental updates.
Organized per target revision (rev_old), covering all commits up to any rev_new.

v19.0.0 (G):
  - CherryDB: SQLite wrapper for cherry-pick results
  - Per-target storage: one DB per rev_old
  - Incremental updates: only test new commits
  - Immutable history: released kernel commits never change
  - Auto-save every 5s during batch operations to avoid data loss

v19.2.0:
  - add_result() now also flushes after BATCH_SIZE (20) pending results,
    whichever of the count or time threshold is hit first.  This bounds
    data loss to at most 20 commits (or 5s) instead of only the time bound,
    which matters for fast batches where 20 results could otherwise
    accumulate well within the 5s window.
  - New delete_db() helper: removes the per-target cherry.db file, used by
    the `cp-check --force` command to restart testing from scratch.
"""
import os
import sqlite3
import json
import time
from datetime import datetime, timezone


class CherryDB:
    """SQLite database for cherry-pick test results.
    
    Schema:
      commits (sha TEXT PRIMARY KEY, ok INTEGER, conflicts TEXT, error TEXT, tested_at TEXT)
    
    Usage:
      db = CherryDB('/path/to/cache/v6.1/cherry.db')
      db.add_results({'abc123': {'ok': True, 'conflicts': [], 'error': None}})
      db.save()
      results = db.get_results(['abc123', 'def456'])
    """
    
    # Auto-save interval in seconds
    AUTO_SAVE_INTERVAL = 5.0

    # Auto-save batch size (v19.2.0): flush after this many pending results
    # even if AUTO_SAVE_INTERVAL has not elapsed yet.  Whichever threshold
    # (count or time) is reached first triggers a flush.
    BATCH_SIZE = 20
    
    def __init__(self, db_path):
        """Initialize or open existing database."""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()
        self._pending_results = {}  # Buffer for auto-save
        self._last_save_time = time.time()
    
    def _create_schema(self):
        """Create database schema if not exists."""
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS commits (
                sha TEXT PRIMARY KEY,
                ok INTEGER NOT NULL,
                conflicts TEXT NOT NULL,
                error TEXT,
                tested_at TEXT NOT NULL
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_ok ON commits(ok)')
        self.conn.commit()
    
    def add_result(self, sha, result):
        """Add or update a single cherry-pick result with auto-save.
        
        This method buffers the result and auto-saves whenever either
        threshold is reached, whichever comes first:
          - BATCH_SIZE (20) pending results accumulate, or
          - AUTO_SAVE_INTERVAL (5.0s) has elapsed since the last flush.
        
        Use this for streaming results during batch operations.
        
        Args:
            sha: commit SHA
            result: dict {'ok': bool, 'conflicts': list, 'error': str or None}
        """
        self._pending_results[sha] = result
        
        now = time.time()
        if (len(self._pending_results) >= self.BATCH_SIZE
                or now - self._last_save_time >= self.AUTO_SAVE_INTERVAL):
            self.flush()
            self._last_save_time = now
    
    def add_results(self, results):
        """Add or update multiple cherry-pick results (immediate commit).
        
        Args:
            results: dict mapping sha -> {'ok': bool, 'conflicts': list, 'error': str or None}
        """
        cursor = self.conn.cursor()
        tested_at = datetime.now(timezone.utc).isoformat()
        
        for sha, result in results.items():
            conflicts_json = json.dumps(result.get('conflicts', []))
            cursor.execute('''
                INSERT OR REPLACE INTO commits (sha, ok, conflicts, error, tested_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                sha,
                1 if result.get('ok', False) else 0,
                conflicts_json,
                result.get('error'),
                tested_at
            ))
        
        self.conn.commit()
    
    def flush(self):
        """Flush pending results to database (called automatically every 5s
        or every BATCH_SIZE results, whichever comes first)."""
        if self._pending_results:
            self.add_results(self._pending_results)
            self._pending_results = {}
    
    def get_results(self, shas):
        """Get cherry-pick results for specified SHAs.
        
        Args:
            shas: list of commit SHAs to look up
        
        Returns:
            dict mapping sha -> {'ok': bool, 'conflicts': list, 'error': str or None}
            Only includes SHAs that exist in the database.
        """
        if not shas:
            return {}
        
        cursor = self.conn.cursor()
        placeholders = ','.join('?' * len(shas))
        cursor.execute(f'SELECT sha, ok, conflicts, error FROM commits WHERE sha IN ({placeholders})', shas)
        
        results = {}
        for row in cursor.fetchall():
            results[row['sha']] = {
                'ok': bool(row['ok']),
                'conflicts': json.loads(row['conflicts']),
                'error': row['error'],
            }
        
        return results
    
    def get_all_shas(self):
        """Get all SHAs in the database.
        
        Returns:
            set of all commit SHAs that have been tested
        """
        cursor = self.conn.cursor()
        cursor.execute('SELECT sha FROM commits')
        return {row['sha'] for row in cursor.fetchall()}
    
    def count(self):
        """Get total number of commits in database."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM commits')
        return cursor.fetchone()[0]
    
    def save(self):
        """Save pending results and close database."""
        self.flush()
        self.conn.commit()
        self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.save()


def get_cherry_db_path(cache_dir, rev_old):
    """Get path to cherry-pick database for a target revision.
    
    Args:
        cache_dir: base cache directory (e.g., '/path/to/cherry-cache')
        rev_old: target revision (e.g., 'v6.1')
    
    Returns:
        full path to cherry.db file
    """
    return os.path.join(cache_dir, rev_old, 'cherry.db')


def ensure_cache_dir(cache_dir, rev_old):
    """Ensure cache directory exists for a target revision.
    
    Args:
        cache_dir: base cache directory
        rev_old: target revision
    
    Returns:
        path to the revision-specific cache directory
    """
    rev_dir = os.path.join(cache_dir, rev_old)
    os.makedirs(rev_dir, exist_ok=True)
    return rev_dir


def load_or_create_db(cache_dir, rev_old):
    """Load existing database or create new one.
    
    Args:
        cache_dir: base cache directory
        rev_old: target revision
    
    Returns:
        CherryDB instance
    """
    db_path = get_cherry_db_path(cache_dir, rev_old)
    ensure_cache_dir(cache_dir, rev_old)
    return CherryDB(db_path)


def delete_db(cache_dir, rev_old):
    """Delete the cherry-pick database for a target revision, if present.

    Used by the ``cp-check --force`` command to clear cached results and
    restart testing from scratch.  Silently no-ops if the file does not
    exist.

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
