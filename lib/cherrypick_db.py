"""Cherry-pick cache database for kcommit-analysis-pipeline.

Stores cherry-pick test results in SQLite for efficient incremental updates.
Organized per target revision (rev_old), covering all commits up to any rev_new.

v19.0.0 (G):
  - CherryDB: SQLite wrapper for cherry-pick results
  - Per-target storage: one DB per rev_old
  - Incremental updates: only test new commits
  - Immutable history: released kernel commits never change
"""
import os
import sqlite3
import json
from datetime import datetime


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
    
    def __init__(self, db_path):
        """Initialize or open existing database."""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_schema()
    
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
    
    def add_results(self, results):
        """Add or update cherry-pick results.
        
        Args:
            results: dict mapping sha -> {'ok': bool, 'conflicts': list, 'error': str or None}
        """
        cursor = self.conn.cursor()
        tested_at = datetime.utcnow().isoformat()
        
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
        """Save and close database."""
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