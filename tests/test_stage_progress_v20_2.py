"""Progress reporting of stages 0 and 1 (v20.2.0)."""
from unittest.mock import patch

from lib.stages import st00_prepare, st01_collect


def _capture(calls):
    def _progress(index, total, frac, label, n_done=None, n_total=None):
        calls.append({'index': index, 'frac': frac, 'label': label,
                      'n_done': n_done, 'n_total': n_total})
    return _progress


def test_stage0_reports_milestones_from_start_to_full_bar(tmp_path):
    calls = []
    with patch.object(st00_prepare, 'validate_inputs', return_value=([], [])), \
         patch.object(st00_prepare, 'compile_rules_for_config', return_value={}), \
         patch.object(st00_prepare, 'active_profile_names', return_value=[]), \
         patch.object(st00_prepare, 'update_stage_progress', side_effect=_capture(calls)), \
         patch.object(st00_prepare, 'finish_progress_line') as finish:
        st00_prepare.run({}, str(tmp_path))
    assert {c['index'] for c in calls} == {0}
    fractions = [c['frac'] for c in calls]
    assert fractions == sorted(fractions) and fractions[0] < 0.1 and fractions[-1] == 1.0
    assert calls[0]['label'] == 'validating configuration'
    finish.assert_called_once()


def test_stage0_validation_error_still_exits(tmp_path):
    with patch.object(st00_prepare, 'validate_inputs', return_value=(['bad'], [])), \
         patch.object(st00_prepare, 'update_stage_progress'):
        try:
            st00_prepare.run({}, str(tmp_path))
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError('SystemExit expected')


def _records(n):
    return [{'commit': '%040x' % i, 'subject': 's', 'files': [], 'numstat': []} for i in range(n)]


def _cfg(**collect):
    return {'kernel': {'source_dir': '/repo', 'rev_old': 'v1', 'rev_new': 'v2'},
            'collect': dict({'include_parents': False}, **collect)}


def _run_collect(tmp_path, records, count, **collect):
    calls = []
    with patch.object(st01_collect, 'iter_git_log_records', return_value=records), \
         patch.object(st01_collect, 'batch_count_hunks', return_value={}), \
         patch.object(st01_collect, 'count_rev_commits', return_value=count), \
         patch.object(st01_collect, 'set_run_size') as run_size, \
         patch.object(st01_collect, 'update_stage_progress', side_effect=_capture(calls)):
        st01_collect.run(_cfg(**collect), str(tmp_path))
    return [c for c in calls if c['label'] == 'collecting commits'], run_size


def test_collection_has_a_determinate_total_from_rev_list_count(tmp_path):
    calls, run_size = _run_collect(tmp_path, _records(60), count=60)
    assert calls[0]['n_total'] == 60 and calls[0]['n_done'] == 0
    assert any(c['n_done'] == 25 and c['n_total'] == 60 for c in calls)
    assert calls[-1]['frac'] == 1.0 and calls[-1]['n_done'] == 60
    run_size.assert_called_once_with(60)


def test_collection_total_is_capped_by_max_commits(tmp_path):
    calls, run_size = _run_collect(tmp_path, _records(30), count=500, max_commits=30)
    assert calls[0]['n_total'] == 30
    run_size.assert_called_once_with(30)


def test_collection_falls_back_to_a_spinner_when_the_count_is_unknown(tmp_path):
    calls, run_size = _run_collect(tmp_path, _records(60), count=None)
    assert calls[0]['n_total'] is None
    assert any(c['n_done'] == 25 and c['n_total'] is None for c in calls)
    run_size.assert_not_called()


def test_collection_total_grows_when_git_reports_more_than_counted(tmp_path):
    calls, _ = _run_collect(tmp_path, _records(60), count=40)
    assert all(c['n_total'] is None or c['n_total'] >= c['n_done'] for c in calls)
