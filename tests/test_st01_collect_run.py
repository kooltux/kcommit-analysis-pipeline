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
    with patch('lib.stages.st01_collect.iter_git_log_records', return_value=records), \
         patch('lib.stages.st01_collect.batch_count_hunks', return_value={}):
        result = run(_cfg(tmp_path), str(cache))
    assert len(result) == 1
    row = result[0]
    assert row['commit'] == 'a'*40
    assert row['subject'] == 'fix'
    assert row['body'] == ''
    assert row['files'] == []
    assert row['numstat'] == []
    assert row['stats'] == {'files_changed': 0, 'insertions': 0,
                            'deletions': 0, 'lines_changed': 0, 'hunks': 0}
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
    with patch('lib.stages.st01_collect.iter_git_log_records', return_value=records), \
         patch('lib.stages.st01_collect.batch_count_hunks', return_value={}):
        result = run(_cfg(tmp_path), str(cache))
    stats = result[0]['stats']
    assert stats['files_changed'] == 2
    assert stats['insertions'] == 15
    assert stats['deletions'] == 2
    assert stats['lines_changed'] == 17
    assert stats['hunks'] == 0


def test_st01_collect_files_changed_falls_back_to_files_len_in_name_only(tmp_path):
    # In --name-only mode numstat is empty; files_changed derives from files.
    cache = tmp_path / 'cache'
    cache.mkdir()
    records = [{
        'commit': 'c' * 40, 'subject': 'name-only',
        'files': ['x.c', 'y.c', 'z.c'],
        'numstat': [],
    }]
    with patch('lib.stages.st01_collect.iter_git_log_records', return_value=records), \
         patch('lib.stages.st01_collect.batch_count_hunks', return_value={}):
        result = run(_cfg(tmp_path), str(cache))
    stats = result[0]['stats']
    assert stats['files_changed'] == 3
    assert stats['lines_changed'] == 0
    assert stats['hunks'] == 0


# ── v19.9.1: hunk-counting progress wiring ─────────────────────────────

def test_st01_collect_passes_progress_callback_to_batch_count_hunks(tmp_path):
    """batch_count_hunks() must be called with a real (non-None) progress_callback."""
    cache = tmp_path / 'cache'
    cache.mkdir()
    records = [{'commit': 'a' * 40, 'subject': 'fix', 'files': [], 'numstat': []}]

    captured = {}

    def _fake_batch_count_hunks(cfg, shas, progress_callback=None):
        captured['callback'] = progress_callback
        captured['shas'] = shas
        return {sha: 0 for sha in shas}

    with patch('lib.stages.st01_collect.iter_git_log_records', return_value=records), \
         patch('lib.stages.st01_collect.batch_count_hunks', side_effect=_fake_batch_count_hunks):
        run(_cfg(tmp_path), str(cache))

    assert captured['callback'] is not None
    assert callable(captured['callback'])
    assert captured['shas'] == ['a' * 40]


def test_st01_collect_hunk_progress_callback_drives_update_stage_progress(tmp_path):
    """Invoking batch_count_hunks' progress_callback must call update_stage_progress
    with the real n_done/n_total (not silence)."""
    cache = tmp_path / 'cache'
    cache.mkdir()
    shas = ['%040x' % i for i in range(160)]
    records = [{'commit': sha, 'subject': 's', 'files': [], 'numstat': []} for sha in shas]

    progress_calls = []

    def _capture_progress(index, total, frac, label, n_done=None, n_total=None):
        progress_calls.append({
            'index': index, 'total': total, 'frac': frac, 'label': label,
            'n_done': n_done, 'n_total': n_total,
        })

    def _fake_batch_count_hunks(cfg, shas, progress_callback=None):
        total = len(shas)
        for i, sha in enumerate(shas, 1):
            if progress_callback:
                progress_callback(i, total)
        return {sha: 0 for sha in shas}

    with patch('lib.stages.st01_collect.iter_git_log_records', return_value=records), \
         patch('lib.stages.st01_collect.batch_count_hunks', side_effect=_fake_batch_count_hunks), \
         patch('lib.stages.st01_collect.update_stage_progress', side_effect=_capture_progress):
        run(_cfg(tmp_path), str(cache))

    hunk_calls = [c for c in progress_calls if c['label'] == 'counting hunks']
    assert len(hunk_calls) > 0
    # The final hunk-progress call must report full completion with a real total.
    last = hunk_calls[-1]
    assert last['n_done'] == 160
    assert last['n_total'] == 160
    assert last['frac'] == 1.0


def test_st01_collect_hunk_counting_skipped_when_no_commits(tmp_path):
    """batch_count_hunks() is never called when there are no collected commits."""
    cache = tmp_path / 'cache'
    cache.mkdir()
    with patch('lib.stages.st01_collect.iter_git_log_records', return_value=[]), \
         patch('lib.stages.st01_collect.batch_count_hunks') as mock_bch:
        result = run(_cfg(tmp_path), str(cache))
    assert result == []
    mock_bch.assert_not_called()


def test_st01_collect_hunk_counts_applied_to_stats(tmp_path):
    """Hunk counts returned by batch_count_hunks() are written into stats['hunks']."""
    cache = tmp_path / 'cache'
    cache.mkdir()
    records = [{'commit': 'd' * 40, 'subject': 'x', 'files': ['a.c'], 'numstat': []}]

    with patch('lib.stages.st01_collect.iter_git_log_records', return_value=records), \
         patch('lib.stages.st01_collect.batch_count_hunks', return_value={'d' * 40: 7}):
        result = run(_cfg(tmp_path), str(cache))

    assert result[0]['stats']['hunks'] == 7
