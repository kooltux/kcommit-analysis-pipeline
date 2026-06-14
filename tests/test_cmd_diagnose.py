"""Tests for lib/commands/cmd_diagnose.py.

All tests call diagnose_commit(cache_dir, sha_query) directly.
No config file, no load_cfg, no profile loading.

Coverage:
  - commit found in each of the 5 cache pools (relevant, postfilter_dropped,
    scored, prefilter_kept, filtered) and in raw commits.json only
  - commit not found at all
  - stage_04_prefilter: dropped path with full layer detail
  - stage_04_prefilter: kept path (no debug stored)
  - stage_05_scoring:  full trace (trace.profiles), compact fallback
  - stage_06_postfilter: kept, dropped, not_run
  - kernel_annotations from commit.meta
  - SHA ambiguity warning
  - final section: stage_reached, in_report, summary strings
  - meta section: required keys, no config/work_dir leakage
  - meta.pipeline_version sourced from prepare_summary.json cache (v16.2.0)
  - meta.pipeline_version fallback for pre-v16.2.0 caches
  - body NOT truncated
  - internal fields absent from commit section
  - search priority (relevant wins over filtered)
  - no cache_presence key in output (removed v14.0.1)
"""
import json
import os

import pytest

from lib.commands.cmd_diagnose import diagnose_commit, _sha_matches, _find
from lib.manifest import CACHE_FILES


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f)


def _cache(tmp_path):
    d = tmp_path / 'cache'
    d.mkdir(exist_ok=True)
    return str(d)


def _make_commit(sha='aabbccdd1122', subject='net: fix skb', files=None,
                 score=None, rank=None, filter_reason=None,
                 prefilter_debug=None, matched_profiles=None,
                 product_evidence=None, scoring=None, meta=None, body=None):
    c = {
        'commit':       sha,
        'subject':      subject,
        'body':         body or 'This is the commit body.',
        'author_name':  'Alice',
        'author_email': 'alice@example.com',
        'author_time':  '2026-01-01',
        'files':        files or ['net/core/sock.c'],
        'stats':        None,
    }
    if score is not None:
        c['score'] = score
    if rank is not None:
        c['_rank'] = rank
    if filter_reason:
        c['_filter_reason'] = filter_reason
    if prefilter_debug:
        c['_prefilter_debug'] = prefilter_debug
    if matched_profiles:
        c['matched_profiles'] = matched_profiles
    if product_evidence:
        c['product_evidence'] = product_evidence
    if scoring:
        c['scoring'] = scoring
    if meta:
        c['meta'] = meta
    return c


def _full_prefilter_debug():
    """Minimal prefilter debug dict matching the v14.1.0 schema."""
    return {
        'filter_enabled':                True,
        'kconfig_required':              True,
        'files':                         ['fs/btrfs/ioctl.c'],
        'l3_commit_wl_match':            None,
        'l3_commit_bl_match':            None,
        'l2a_path_bl_matches':           [],
        'l2half_artifact_files':         [],
        'l2half_kconfig_covered_files':  [],
        'l2half_kconfig_uncovered_files': ['fs/btrfs/ioctl.c'],
    }


def _full_scoring():
    """Return a scoring dict with full trace as written by scoring.py."""
    return {
        'profiles': {'usb': 70},
        'trace': {
            'profiles': {
                'usb': {
                    'final_score':           70,
                    'raw_rule_total':        70,
                    'raw_rule_total_capped': 70,
                    'multiplier':            1.0,
                    'blocked':               False,
                    'block_reason':          '',
                    'merged_matches': {
                        'keywords_whitelist': [{'pattern': 'usb', 'value': 'usb fix'}],
                        'keywords_blacklist': [],
                        'path_whitelist':     [{'pattern': 'drivers/usb/', 'file': 'drivers/usb/core/hub.c'}],
                        'path_blacklist':     [],
                        'commit_whitelist':   [],
                        'commit_blacklist':   [],
                    },
                    'rules': {
                        'rule_usb_fix': {
                            'weight':        70,
                            'matched':       True,
                            'matched_level': 'matched',
                            'score':         70,
                            'matches': {
                                'keywords_whitelist': [{'pattern': 'usb', 'value': 'usb fix'}],
                                'path_whitelist':     [],
                                'commit_whitelist':   [],
                            },
                        }
                    },
                }
            }
        }
    }


# ---------------------------------------------------------------------------
# helpers unit tests
# ---------------------------------------------------------------------------

def test_sha_matches_case_insensitive():
    assert _sha_matches('AABBCCDD1122', 'aabb')
    assert not _sha_matches('AABBCCDD1122', 'xxyy')


def test_find_returns_first_match():
    pool = [{'commit': 'aabb0001', 'subject': 'first'},
            {'commit': 'aabb0002', 'subject': 'second'}]
    assert _find(pool, 'aabb')['subject'] == 'first'


def test_find_no_match():
    assert _find([{'commit': 'deadbeef'}], 'cafe') is None


# ---------------------------------------------------------------------------
# search-order priority
# ---------------------------------------------------------------------------

def test_relevant_wins_over_all_lower_stages(tmp_path):
    cache = _cache(tmp_path)
    sha = 'aabbccdd1122'
    _write(os.path.join(cache, CACHE_FILES['relevant']),
           [_make_commit(sha=sha, subject='from relevant', score=80, rank=1)])
    _write(os.path.join(cache, CACHE_FILES['filtered']),
           [_make_commit(sha=sha, subject='from filtered',
                         filter_reason='no_kconfig_coverage')])

    r = diagnose_commit(cache, 'aabbccdd')
    assert r['final']['stage_reached'] == 'relevant'
    assert r['commit']['subject'] == 'from relevant'


def test_postfilter_dropped_wins_over_scored(tmp_path):
    cache = _cache(tmp_path)
    sha = 'aabbccdd1122'
    _write(os.path.join(cache, CACHE_FILES['postfilter_dropped']),
           [_make_commit(sha=sha, subject='from pf_dropped',
                         score=5, filter_reason='score_below_threshold')])
    _write(os.path.join(cache, CACHE_FILES['scored']),
           [_make_commit(sha=sha, subject='from scored', score=5)])

    r = diagnose_commit(cache, 'aabbccdd')
    assert r['final']['stage_reached'] == 'postfilter_dropped'


# ---------------------------------------------------------------------------
# commit found in relevant
# ---------------------------------------------------------------------------

def test_found_in_relevant(tmp_path):
    cache = _cache(tmp_path)
    commit = _make_commit(
        sha='aabbccdd1122', subject='usb: fix hub crash',
        score=85, rank=3,
        matched_profiles=['usb'],
        product_evidence=['config_map:CONFIG_USB'],
        scoring=_full_scoring(),
        meta={'is_fix': True, 'has_cve': False, 'has_syzbot': False, 'has_stable_cc': True},
    )
    _write(os.path.join(cache, CACHE_FILES['relevant']), [commit])
    _write(os.path.join(cache, CACHE_FILES['postfilter_debug']),
           {'summary': {'threshold': 20.0}})

    r = diagnose_commit(cache, 'aabbccdd')

    assert r['final']['stage_reached'] == 'relevant'
    assert r['final']['in_report'] is True
    assert r['final']['rank'] == 3
    assert r['final']['score'] == 85
    assert 'rank 3' in r['final']['summary']

    assert r['commit']['sha'] == 'aabbccdd1122'
    assert r['commit']['sha12'] == 'aabbccdd1122'
    assert r['commit']['subject'] == 'usb: fix hub crash'
    assert r['commit']['author_name'] == 'Alice'

    assert r['kernel_annotations']['is_fix'] is True
    assert r['kernel_annotations']['has_stable_cc'] is True
    assert r['kernel_annotations']['has_cve'] is False

    assert r['pipeline_stages']['stage_04_prefilter']['outcome'] == 'kept'
    assert r['pipeline_stages']['stage_04_prefilter']['layers'] is None

    s05 = r['pipeline_stages']['stage_05_scoring']
    assert s05 is not None
    assert s05['total_score'] == 85
    assert 'usb' in s05['profiles']
    usb = s05['profiles']['usb']
    assert usb['final_score'] == 70
    assert usb['multiplier'] == 1.0
    assert usb['blocked'] is False
    assert 'rule_usb_fix' in usb['rules']
    assert usb['rules']['rule_usb_fix']['matched'] is True
    assert usb['rules']['rule_usb_fix']['score'] == 70

    s06 = r['pipeline_stages']['stage_06_postfilter']
    assert s06['outcome'] == 'kept'
    assert s06['threshold'] == 20.0
    assert s06['rank'] == 3


# ---------------------------------------------------------------------------
# commit found in postfilter_dropped
# ---------------------------------------------------------------------------

def test_found_in_postfilter_dropped(tmp_path):
    cache = _cache(tmp_path)
    commit = _make_commit(
        sha='deadbeef1234', subject='btrfs: minor cleanup',
        score=5, filter_reason='score_below_threshold',
        scoring=_full_scoring(),
    )
    _write(os.path.join(cache, CACHE_FILES['postfilter_dropped']), [commit])
    _write(os.path.join(cache, CACHE_FILES['postfilter_debug']),
           {'summary': {'threshold': 20.0}})

    r = diagnose_commit(cache, 'deadbeef')

    assert r['final']['stage_reached'] == 'postfilter_dropped'
    assert r['final']['in_report'] is False
    s06 = r['pipeline_stages']['stage_06_postfilter']
    assert s06['outcome'] == 'dropped'
    assert s06['threshold'] == 20.0
    assert s06['score'] == 5
    assert r['pipeline_stages']['stage_05_scoring'] is not None


# ---------------------------------------------------------------------------
# commit found in filtered (dropped at prefilter)
# ---------------------------------------------------------------------------

def test_found_in_filtered_full_layer_detail(tmp_path):
    cache = _cache(tmp_path)
    dbg = _full_prefilter_debug()
    commit = _make_commit(
        sha='b238eaa15369',
        subject='btrfs: reschedule when cloning lots of extents',
        files=['fs/btrfs/ioctl.c'],
        filter_reason='no_kconfig_coverage',
        prefilter_debug=dbg,
    )
    _write(os.path.join(cache, CACHE_FILES['filtered']), [commit])

    r = diagnose_commit(cache, 'b238eaa1')

    assert r['final']['stage_reached'] == 'filtered'
    assert r['final']['in_report'] is False
    assert 'Reason: no_kconfig_coverage' in r['final']['summary']

    s04 = r['pipeline_stages']['stage_04_prefilter']
    assert s04['outcome'] == 'dropped'
    assert s04['reason'] == 'no_kconfig_coverage'
    assert s04['filter_enabled'] is True
    assert s04['kconfig_required'] is True

    layers = s04['layers']
    assert layers['L3_sha_whitelist'] is None
    assert layers['L3_sha_blacklist'] is None
    assert layers['L2a_path_bl_matches'] == []
    assert layers['L2half_artifact_files'] == []
    assert 'fs/btrfs/ioctl.c' in layers['L2half_kconfig_uncovered_files']
    assert layers['L2half_kconfig_covered_files'] == []

    # v14.1.0: these stale fields must not appear in layers
    assert 'L2b_path_wl_matches' not in layers
    assert 'L1a_kw_wl_matches' not in layers
    assert 'L1b_kw_bl_matches' not in layers
    assert 'kw_wl_rescue_suppressed' not in layers

    # no scoring or postfilter for dropped commit
    assert r['pipeline_stages']['stage_05_scoring'] is None
    assert r['pipeline_stages']['stage_06_postfilter'] is None


# ---------------------------------------------------------------------------
# commit found only in prefilter_kept
# ---------------------------------------------------------------------------

def test_found_in_prefilter_kept(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['prefilter_kept']),
           [_make_commit(sha='cafebabe0001', subject='usb: fix suspend')])

    r = diagnose_commit(cache, 'cafebabe')

    assert r['final']['stage_reached'] == 'prefilter_kept'
    assert r['final']['in_report'] is False
    assert r['pipeline_stages']['stage_04_prefilter']['outcome'] == 'kept'
    assert r['pipeline_stages']['stage_05_scoring'] is None
    assert r['pipeline_stages']['stage_06_postfilter'] is None


# ---------------------------------------------------------------------------
# commit found only in raw commits.json
# ---------------------------------------------------------------------------

def test_found_in_commits_only(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['commits']),
           [_make_commit(sha='11223344aabb', subject='net: add rx queue stats')])

    r = diagnose_commit(cache, '11223344')

    assert r['final']['stage_reached'] == 'commits_only'
    assert r['final']['in_report'] is False
    assert any('raw commits' in w for w in r['warnings'])


# ---------------------------------------------------------------------------
# commit not found
# ---------------------------------------------------------------------------

def test_not_found(tmp_path):
    cache = _cache(tmp_path)
    r = diagnose_commit(cache, 'deadbeef')

    assert r['final']['stage_reached'] == 'not_found'
    assert r['final']['in_report'] is False
    assert any('not found' in w for w in r['warnings'])
    assert r['commit']['sha'] == 'deadbeef'


# ---------------------------------------------------------------------------
# stage_01_collect
# ---------------------------------------------------------------------------

def test_stage01_found_true_when_in_commits(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['commits']),
           [_make_commit(sha='aabbccdd1122')])
    r = diagnose_commit(cache, 'aabbccdd')
    assert r['pipeline_stages']['stage_01_collect']['found'] is True


def test_stage01_found_false_when_not_in_commits(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['relevant']),
           [_make_commit(sha='aabbccdd1122', score=50, rank=1)])
    r = diagnose_commit(cache, 'aabbccdd')
    assert r['pipeline_stages']['stage_01_collect']['found'] is False


# ---------------------------------------------------------------------------
# kernel annotations
# ---------------------------------------------------------------------------

def test_kernel_annotations_all_false_default(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['filtered']),
           [_make_commit(sha='aabbccdd1122', filter_reason='no_kconfig_coverage')])
    r = diagnose_commit(cache, 'aabbccdd')
    ann = r['kernel_annotations']
    assert ann['is_fix'] is False
    assert ann['has_cve'] is False
    assert ann['has_syzbot'] is False
    assert ann['has_stable_cc'] is False


def test_kernel_annotations_read_from_meta(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['relevant']),
           [_make_commit(sha='aabbccdd1122', score=50, rank=1,
                         meta={'is_fix': True, 'has_cve': True,
                               'has_syzbot': False, 'has_stable_cc': False})])
    r = diagnose_commit(cache, 'aabbccdd')
    assert r['kernel_annotations']['is_fix'] is True
    assert r['kernel_annotations']['has_cve'] is True


# ---------------------------------------------------------------------------
# commit section: body NOT truncated, internal fields stripped
# ---------------------------------------------------------------------------

def test_commit_body_not_truncated(tmp_path):
    cache = _cache(tmp_path)
    long_body = 'x' * 2000
    c = _make_commit(sha='aabbccdd1122', score=10, rank=1, body=long_body)
    _write(os.path.join(cache, CACHE_FILES['relevant']), [c])

    r = diagnose_commit(cache, 'aabbccdd')
    assert len(r['commit']['body']) == 2000


def test_commit_section_has_no_internal_fields(tmp_path):
    cache = _cache(tmp_path)
    c = _make_commit(sha='aabbccdd1122', filter_reason='no_kconfig_coverage')
    c['meta'] = {'is_fix': True}
    c['touched_paths_guess'] = ['fs/btrfs/']
    _write(os.path.join(cache, CACHE_FILES['filtered']), [c])

    r = diagnose_commit(cache, 'aabbccdd')
    for k in ('_filter_reason', '_prefilter_debug', 'meta', 'touched_paths_guess',
              '_rank', '_postfilter_reason'):
        assert k not in r['commit'], f'Internal key {k!r} must not appear in commit section'


def test_commit_section_required_fields(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['relevant']),
           [_make_commit(sha='aabbccdd1122', score=50, rank=1)])
    r = diagnose_commit(cache, 'aabbccdd')
    for k in ('sha', 'sha12', 'subject', 'author_name', 'author_email',
              'author_time', 'files', 'body'):
        assert k in r['commit'], f'Required field {k!r} missing from commit section'


# ---------------------------------------------------------------------------
# no cache_presence key in output (removed v14.0.1)
# ---------------------------------------------------------------------------

def test_no_cache_presence_in_output(tmp_path):
    cache = _cache(tmp_path)
    r = diagnose_commit(cache, 'aabbccdd')
    assert 'cache_presence' not in r


# ---------------------------------------------------------------------------
# scoring: compact fallback when trace absent
# ---------------------------------------------------------------------------

def test_scoring_compact_fallback(tmp_path):
    """When scoring.trace is absent (older cache), compact form is used."""
    cache = _cache(tmp_path)
    c = _make_commit(
        sha='aabbccdd1122', score=55, rank=1,
        scoring={'profiles': {'net': 55}},
    )
    _write(os.path.join(cache, CACHE_FILES['relevant']), [c])
    r = diagnose_commit(cache, 'aabbccdd')
    s05 = r['pipeline_stages']['stage_05_scoring']
    assert s05 is not None
    assert 'net' in s05['profiles']


# ---------------------------------------------------------------------------
# postfilter: threshold from postfilter_debug.json
# ---------------------------------------------------------------------------

def test_postfilter_threshold_sourced_from_debug_json(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['relevant']),
           [_make_commit(sha='aabb1234ccdd', score=30, rank=1)])
    _write(os.path.join(cache, CACHE_FILES['postfilter_debug']),
           {'summary': {'threshold': 15.0}})

    r = diagnose_commit(cache, 'aabb1234')
    assert r['pipeline_stages']['stage_06_postfilter']['threshold'] == 15.0


def test_postfilter_not_run_when_only_scored(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['scored']),
           [_make_commit(sha='aabbccdd1122', score=40)])
    r = diagnose_commit(cache, 'aabbccdd')
    s06 = r['pipeline_stages']['stage_06_postfilter']
    assert s06['outcome'] == 'not_run'


# ---------------------------------------------------------------------------
# SHA ambiguity warning
# ---------------------------------------------------------------------------

def test_sha_ambiguity_warning(tmp_path):
    cache = _cache(tmp_path)
    c1 = _make_commit(sha='aabb000011', score=50, rank=1)
    c2 = _make_commit(sha='aabb000022', score=40, rank=2)
    _write(os.path.join(cache, CACHE_FILES['relevant']), [c1, c2])

    r = diagnose_commit(cache, 'aabb')
    assert any('ambiguous' in w for w in r['warnings'])


# ---------------------------------------------------------------------------
# meta section
# ---------------------------------------------------------------------------

def test_meta_required_keys(tmp_path):
    cache = _cache(tmp_path)
    r = diagnose_commit(cache, 'aabbccdd')
    for k in ('pipeline_version', 'cache_dir', 'sha_query', 'generated_at'):
        assert k in r['meta']


def test_meta_no_config_or_work_dir(tmp_path):
    cache = _cache(tmp_path)
    r = diagnose_commit(cache, 'aabbccdd')
    assert 'config' not in r['meta']
    assert 'work_dir' not in r['meta']


def test_meta_cache_dir_matches(tmp_path):
    cache = _cache(tmp_path)
    r = diagnose_commit(cache, 'aabbccdd')
    assert r['meta']['cache_dir'] == cache


def test_meta_generated_at_is_utc_iso(tmp_path):
    cache = _cache(tmp_path)
    r = diagnose_commit(cache, 'aabbccdd')
    ts = r['meta']['generated_at']
    assert ts.endswith('Z')
    assert 'T' in ts


def test_meta_pipeline_version_from_prepare_summary(tmp_path):
    """pipeline_version in meta must be read from prepare_summary.json (v16.2.0)."""
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['prepare_summary']),
           {'pipeline_version': 'v99.0.0', 'profiles': [], 'rule_counts': {}})

    r = diagnose_commit(cache, 'aabbccdd')
    assert r['meta']['pipeline_version'] == 'v99.0.0', (
        'pipeline_version must be taken from prepare_summary.json, not the running code'
    )


def test_meta_pipeline_version_fallback_when_prepare_summary_absent(tmp_path):
    """When prepare_summary.json is missing, pipeline_version falls back gracefully."""
    cache = _cache(tmp_path)
    # do NOT write prepare_summary.json

    r = diagnose_commit(cache, 'aabbccdd')
    assert r['meta']['pipeline_version'] == 'unknown (cache predates v16.2.0)', (
        'Fallback version string must be returned when prepare_summary.json is absent'
    )


def test_meta_pipeline_version_fallback_when_key_absent(tmp_path):
    """When prepare_summary.json exists but lacks pipeline_version, fallback is used."""
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['prepare_summary']),
           {'profiles': ['net'], 'rule_counts': {'net': 3}})

    r = diagnose_commit(cache, 'aabbccdd')
    assert r['meta']['pipeline_version'] == 'unknown (cache predates v16.2.0)'


# ---------------------------------------------------------------------------
# final section
# ---------------------------------------------------------------------------

def test_final_in_report_only_for_relevant(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['relevant']),
           [_make_commit(sha='aabbccdd1122', score=50, rank=1)])
    r = diagnose_commit(cache, 'aabbccdd')
    assert r['final']['in_report'] is True


def test_final_not_in_report_for_filtered(tmp_path):
    cache = _cache(tmp_path)
    _write(os.path.join(cache, CACHE_FILES['filtered']),
           [_make_commit(sha='aabbccdd1122',
                         filter_reason='no_kconfig_coverage')])
    r = diagnose_commit(cache, 'aabbccdd')
    assert r['final']['in_report'] is False
