import json
from unittest.mock import patch

from lib.stages.st01_collect import run


def _cfg(tmp_path):
    return {
        'kernel': {'source_dir': '/repo', 'rev_old': 'v1', 'rev_new': 'v2'},
        'collect': {'include_parents': False},
    }


def test_st01_collect_run_writes_cache(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    records = [{'commit': 'a'*40, 'subject': 'fix'}]
    with patch('lib.stages.st01_collect.iter_git_log_records', return_value=records):
        result = run(_cfg(tmp_path), str(cache))
    assert len(result) == 1
    row = result[0]
    assert row['commit'] == 'a'*40
    assert row['subject'] == 'fix'
    assert row['body'] == ''
    assert row['files'] == []
    assert row['numstat'] == []
    assert row['stats'] == {'files_changed': 0, 'insertions': 0,
                            'deletions': 0, 'lines_changed': 0}
    assert row['author_time'] is None
    assert row['commit_time'] is None
    assert row['author_name'] is None
    assert row['author_email'] is None
    data = json.loads((cache / 'commits.json').read_text(encoding='utf-8'))
    assert data == result


def test_st01_collect_stats_from_numstat(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    records = [{
        'commit': 'b' * 40, 'subject': 'big',
        'files': ['a.c', 'b.h'],
        'numstat': [
            {'added': '10', 'deleted': '2', 'path': 'a.c'},
            {'added': '5', 'deleted': '0', 'path': 'b.h'},
        ],
    }]
    with patch('lib.stages.st01_collect.iter_git_log_records', return_value=records):
        result = run(_cfg(tmp_path), str(cache))
    stats = result[0]['stats']
    assert stats['files_changed'] == 2
    assert stats['insertions'] == 15
    assert stats['deletions'] == 2
    assert stats['lines_changed'] == 17


def test_st01_collect_files_changed_falls_back_to_files_len_in_name_only(tmp_path):
    # In --name-only mode numstat is empty; files_changed derives from files.
    cache = tmp_path / 'cache'
    cache.mkdir()
    records = [{
        'commit': 'c' * 40, 'subject': 'name-only',
        'files': ['x.c', 'y.c', 'z.c'],
        'numstat': [],
    }]
    with patch('lib.stages.st01_collect.iter_git_log_records', return_value=records):
        result = run(_cfg(tmp_path), str(cache))
    stats = result[0]['stats']
    assert stats['files_changed'] == 3
    assert stats['lines_changed'] == 0
