from lib.manifest import COMMIT_COLS, COMMIT_COLS_FILTERED, STAGE_OUTPUTS


def test_manifest_filtered_columns_extend_main_columns():
    assert COMMIT_COLS_FILTERED[:-1] == COMMIT_COLS
    assert COMMIT_COLS_FILTERED[-1] == 'Filter Reason'


def test_manifest_has_report_stage_outputs_entry():
    assert 'report_commits' in STAGE_OUTPUTS
    assert isinstance(STAGE_OUTPUTS['report_commits'], list)
