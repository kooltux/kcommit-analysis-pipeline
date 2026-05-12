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
    assert row['author_time'] is None
    assert row['commit_time'] is None
    assert row['author_name'] is None
    assert row['author_email'] is None
    data = json.loads((cache / 'commits.json').read_text(encoding='utf-8'))
    assert data == result
