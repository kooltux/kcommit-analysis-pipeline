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

v19.2.2:
  - Fixed transaction handling: use autocommit mode (isolation_level=None)
    and explicit BEGIN/COMMIT for batch durability. Each batch is committed
    immediately and visible to external queries.
  - Disabled WAL mode (journal_mode=DELETE) to ensure writes are immediately
    visible to external SQLite queries without needing to checkpoint.
  - Each INSERT OR REPLACE is now a single-row transaction committed immediately.

v19.2.3:
  - Removed result buffering: add_result() now flushes immediately after
    each INSERT, ensuring external queries see results as soon as they're
    added. The auto-save timer and batch threshold are kept as safety
    mechanisms but are no longer the primary flush trigger.

v19.8.1:
  - get_results() chunks large SHA `IN (...)` lookups to at most 900 values
    per query (below SQLite's traditional 999-variable ceiling), preventing
    "too many SQL variables" when many commits are scored at once.

v19.9.0:
  - Path/cache-layout helpers (get_cherry_db_path, ensure_cache_dir,
    load_or_create_db, delete_db) moved to lib/cherrypick_paths.py and are
    re-exported here for backward compatibility. The on-disk layout changed
    from a per-revision subdirectory (<cache_dir>/<rev_old>/cherry.db) to a
    single direct file named after the (slash/backslash-normalized) target
    revision (<cache_dir>/<safe-rev_old>). See lib/cherrypick_paths.py for
    details.
"""
import sqlite3
import json
import time
from datetime import datetime, timezone

from lib.cherrypick_paths import (
    get_cherry_db_path,
    ensure_cache_dir,
    load_or_create_db,
    delete_db,
)

__all__ = [
    'CherryDB',
    'get_cherry_db_path',
    'ensure_cache_dir',
    'load_or_create_db',
    'delete_db',
]


# Traditional SQLite builds permit at most 999 bound variables per statement.
# Keep a small margin below that limit for compatibility with older or custom
# SQLite builds. get_results() chunks large SHA lookups to this size.
_RESULT_LOOKUP_CHUNK_SIZE = 900


class CherryDB:
    """SQLite database for cherry-pick test results.
    
    Schema:
      commits (sha TEXT PRIMARY KEY, ok INTEGER, conflicts TEXT, error TEXT, tested_at TEXT)
    
    Usage:
      db = CherryDB('/path/to/cache/v6.1.1')
      db.add_results({'abc123': {'ok': True, 'conflicts': [], 'error': None}})
      db.save()
      results = db.get_results(['abc123', 'def456'])
    """
    
    AUTO_SAVE_INTERVAL = 5.0
    BATCH_SIZE = 20
    
    def __init__(self, db_path):
        """Initialize or open existing database."""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._disable_wal_mode()
        self._create_schema()
        self._pending_results = {}
        self._last_save_time = time.time()
    
    def _disable_wal_mode(self):
        """Disable WAL mode and checkpoint existing WAL file if present."""
        self.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        self.conn.execute('PRAGMA journal_mode=DELETE')
    
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
    
    def add_result(self, sha, result):
        """Add or update a single cherry-pick result with immediate flush."""
        self._pending_results[sha] = result
        self.flush()
        self._last_save_time = time.time()
        now = time.time()
        if (len(self._pending_results) >= self.BATCH_SIZE
                or now - self._last_save_time >= self.AUTO_SAVE_INTERVAL):
            self._last_save_time = now
    
    def add_results(self, results):
        """Add or update multiple cherry-pick results."""
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
    
    def flush(self):
        """Flush pending results to database."""
        if self._pending_results:
            self.add_results(self._pending_results)
            self._pending_results = {}
    
    def get_results(self, shas):
        """Get cached cherry-pick results for specified SHAs (chunked lookup)."""
        seen = set()
        unique_shas = []
        for sha in shas or []:
            if sha and sha not in seen:
                seen.add(sha)
                unique_shas.append(sha)
        if not unique_shas:
            return {}

        cursor = self.conn.cursor()
        results = {}
        for start in range(0, len(unique_shas), _RESULT_LOOKUP_CHUNK_SIZE):
            chunk = unique_shas[start:start + _RESULT_LOOKUP_CHUNK_SIZE]
            placeholders = ','.join('?' * len(chunk))
            cursor.execute(
                f'SELECT sha, ok, conflicts, error FROM commits WHERE sha IN ({placeholders})',
                chunk,
            )
            for row in cursor.fetchall():
                results[row['sha']] = {
                    'ok': bool(row['ok']),
                    'conflicts': json.loads(row['conflicts']),
                    'error': row['error'],
                }
        return results
    
    def get_all_shas(self):
        """Get all SHAs in the database."""
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
        self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.save()
