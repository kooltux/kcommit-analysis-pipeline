"""Tests for lib.manifest -- CACHE_FILES, column lists, STAGE_OUTPUTS.

v13.0.0 (E.7): added assertion that CACHE_FILES['postfilter_debug'] exists.
"""
from lib.manifest import COMMIT_COLS, COMMIT_COLS_FILTERED, STAGE_OUTPUTS, CACHE_FILES


def test_manifest_filtered_columns_extend_main_columns():
    assert COMMIT_COLS_FILTERED[:-1] == COMMIT_COLS
    assert COMMIT_COLS_FILTERED[-1] == 'Filter Reason'


def test_manifest_has_report_stage_outputs_entry():
    assert 'report_commits' in STAGE_OUTPUTS
    assert isinstance(STAGE_OUTPUTS['report_commits'], list)


def test_cache_files_has_prefilter_debug_key():
    """A.1: CACHE_FILES must expose 'prefilter_debug'."""
    assert 'prefilter_debug' in CACHE_FILES
    assert CACHE_FILES['prefilter_debug'].endswith('.json')


def test_cache_files_has_postfilter_debug_key():
    """E.7: CACHE_FILES must expose 'postfilter_debug'."""
    assert 'postfilter_debug' in CACHE_FILES
    assert CACHE_FILES['postfilter_debug'].endswith('.json')


def test_cache_files_all_values_are_strings():
    """All CACHE_FILES values must be non-empty filename strings."""
    for key, val in CACHE_FILES.items():
        assert isinstance(val, str) and val, \
            'CACHE_FILES[%r] is not a non-empty string: %r' % (key, val)


def test_cache_files_core_keys_present():
    """Smoke-test that the core pipeline cache keys are all present."""
    required = {
        'commits', 'build_context', 'product_map',
        'prefilter_kept', 'prefilter_debug', 'filtered',
        'scored', 'relevant', 'postfilter_dropped', 'postfilter_debug',
    }
    missing = required - set(CACHE_FILES.keys())
    assert not missing, 'CACHE_FILES is missing keys: %s' % sorted(missing)
