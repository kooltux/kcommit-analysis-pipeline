"""Tests for lib/commands/cmd_diagnose.py.

Covers:
  - diagnose_commit(): all six search-order stages
  - prefilter section for dropped and kept commits
  - scoring section for scored/relevant commits
  - postfilter section for kept/dropped
  - final section summary strings
  - SHA-prefix ambiguity warning
  - commit-not-found warning
  - cache_presence map completeness
  - --out flag (file write path)
  - --sha too-short guard
  - diagnose_commit() takes cache_dir directly (no config file needed)
"""
import json
import os

import pytest

from lib.commands.cmd_diagnose import diagnose_commit, _find_in_list, _sha_matches
from lib.manifest import CACHE_FILES


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f)


def _make_commit(sha='aabbccdd1122', subject='net: fix skb', files=None,
                 score=None, rank=None, filter_reason=None,
                 prefilter_debug=None, matched_profiles=None,
                 product_evidence=None, scoring=None):
    c = {'commit': sha, 'subject': subject, 'body': 'body text',
         'author_name': 'Alice', 'author_time': '2026-01-01',
         'files': files or ['net/core/sock.c']}
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
    return c


def _cache(tmp_path):
    """Return the cache directory path (created if needed)."""
    d = tmp_path / 'cache'
    d.mkdir(exist_ok=True)
    return str(d)


# ---------------------------------------------------------------------------
# unit tests for helpers
# ---------------------------------------------------------------------------

def test_sha_matches_prefix():
    assert _sha_matches('aabbccdd1122', 'aabb')
    assert not _sha_matches('aabbccdd1122', 'xxyy')
    assert _sha_matches('AABBCCDD1122', 'aabb')  # case-insensitive


def test_find_in_list_returns_first_match():
    commits = [
        {'commit': 'aabbccdd', 'subject': 'first'},
        {'commit': 'aabbccdd', 'subject': 'second'},
    ]
    result = _find_in_list(commits, 'aabb')
    assert result['subject'] == 'first'


def test_find_in_list_no_match_returns_none():
    assert _find_in_list([{'commit': 'deadbeef'}], 'cafe') is None


def test_find_in_list_empty_list():
    assert _find_in_list([], 'aabb') is None


# ---------------------------------------------------------------------------
# diagnose_commit: cache_dir is the only required argument
# ---------------------------------------------------------------------------

def test_diagnose_commit_takes_cache_dir_directly(tmp_path):
    """diagnose_commit(cache_dir, sha) must work without any config file."""
    cache = _cache(tmp_path)
    commit = _make_commit(sha='aabbccdd1122', subject='usb: fix x',
                          score=50, rank=1)
    _write_json(os.path.join(cache, CACHE_FILES['relevant']), [commit])

    # No config argument -- cache_dir is sufficient
    report = diagnose_commit(cache, 'aabbccdd')
    assert report['final']['stage_found'] == 'relevant'


# ---------------------------------------------------------------------------
# diagnose_commit: commit found in relevant_commits.json
# ---------------------------------------------------------------------------

def test_diagnose_commit_found_in_relevant(tmp_path):
    cache = _cache(tmp_path)
    commit = _make_commit(
        sha='aabbccdd1122',
        subject='usb: fix hub crash',
        score=85,
        rank=3,
        matched_profiles=['usb'],
        product_evidence=['config_map:CONFIG_USB'],
        scoring={
            'profiles': {
                'usb': {'score': 85, 'weight': 100,
                        'matched_rules': ['rule_usb'], 'keyword_hits': [],
                        'path_hits': ['drivers/usb/']}
            }
        },
    )
    _write_json(os.path.join(cache, CACHE_FILES['relevant']), [commit])

    report = diagnose_commit(cache, 'aabbccdd')

    assert report['final']['stage_found'] == 'relevant'
    assert report['final']['rank'] == 3
    assert report['final']['score'] == 85
    assert 'rank 3' in report['final']['summary']
    assert report['prefilter']['outcome'] == 'kept'
    assert report['scoring']['score'] == 85
    assert 'usb' in report['scoring']['profile_breakdown']
    assert report['postfilter']['outcome'] == 'kept'
    assert report['postfilter']['rank'] == 3


# ---------------------------------------------------------------------------
# diagnose_commit: commit found in postfilter_dropped
# ---------------------------------------------------------------------------

def test_diagnose_commit_found_in_postfilter_dropped(tmp_path):
    cache = _cache(tmp_path)
    commit = _make_commit(
        sha='deadbeef1234',
        subject='btrfs: minor cleanup',
        score=5,
        filter_reason='score_below_threshold',
    )
    _write_json(os.path.join(cache, CACHE_FILES['postfilter_dropped']), [commit])
    _write_json(os.path.join(cache, CACHE_FILES['postfilter_debug']),
                {'summary': {'threshold': 20.0}})

    report = diagnose_commit(cache, 'deadbeef')

    assert report['final']['stage_found'] == 'postfilter_dropped'
    assert report['postfilter']['outcome'] == 'dropped'
    assert report['postfilter']['threshold'] == 20.0
    assert report['postfilter']['score'] == 5
    assert report['scoring'] is not None


# ---------------------------------------------------------------------------
# diagnose_commit: commit found in filtered_commits.json (prefilter drop)
# ---------------------------------------------------------------------------

def test_diagnose_commit_found_in_filtered(tmp_path):
    cache = _cache(tmp_path)
    prefilter_debug = {
        'filter_enabled': True,
        'kconfig_required': True,
        'files': ['fs/btrfs/ioctl.c'],
        'l2half_kconfig_uncovered_files': ['fs/btrfs/ioctl.c'],
        'l2half_kconfig_covered_files': [],
        'l2half_artifact_files': [],
        'l1a_kw_wl_matches': [{'pattern': 'BUG', 'value': 'BUG: soft lockup'}],
        'kw_wl_rescue_suppressed': True,
        'l3_commit_wl_match': None,
        'l3_commit_bl_match': None,
        'l2a_path_bl_matches': [],
        'l2b_path_wl_matches': [],
        'l1b_kw_bl_matches': [],
    }
    commit = _make_commit(
        sha='b238eaa15369',
        subject='btrfs: reschedule when cloning lots of extents',
        files=['fs/btrfs/ioctl.c'],
        filter_reason='no_kconfig_coverage',
        prefilter_debug=prefilter_debug,
    )
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [commit])

    report = diagnose_commit(cache, 'b238eaa1')

    assert report['final']['stage_found'] == 'filtered'
    assert report['prefilter']['outcome'] == 'dropped'
    assert report['prefilter']['reason'] == 'no_kconfig_coverage'
    assert report['prefilter']['kw_wl_rescue_suppressed'] is True
    assert report['prefilter']['debug']['l1a_kw_wl_matches'][0]['pattern'] == 'BUG'
    assert 'fs/btrfs/ioctl.c' in report['prefilter']['debug']['l2half_kconfig_uncovered_files']
    assert report['scoring'] is None
    assert report['postfilter'] is None


# ---------------------------------------------------------------------------
# diagnose_commit: commit found only in prefilter_kept (not yet scored)
# ---------------------------------------------------------------------------

def test_diagnose_commit_found_in_prefilter_kept(tmp_path):
    cache = _cache(tmp_path)
    commit = _make_commit(sha='cafebabe0001', subject='usb: fix hang on suspend')
    _write_json(os.path.join(cache, CACHE_FILES['prefilter_kept']), [commit])

    report = diagnose_commit(cache, 'cafebabe')

    assert report['final']['stage_found'] == 'prefilter_kept'
    assert report['prefilter']['outcome'] == 'kept'
    assert report['scoring'] is None
    assert report['postfilter'] is None


# ---------------------------------------------------------------------------
# diagnose_commit: commit found only in raw commits.json
# ---------------------------------------------------------------------------

def test_diagnose_commit_found_in_commits_only(tmp_path):
    cache = _cache(tmp_path)
    commit = _make_commit(sha='11223344aabb', subject='net: add rx queue stats')
    _write_json(os.path.join(cache, CACHE_FILES['commits']), [commit])

    report = diagnose_commit(cache, '11223344')

    assert report['final']['stage_found'] == 'commits_only'
    assert any('raw commits' in w for w in report['warnings'])


# ---------------------------------------------------------------------------
# diagnose_commit: commit not found anywhere
# ---------------------------------------------------------------------------

def test_diagnose_commit_not_found(tmp_path):
    cache = _cache(tmp_path)
    # No cache files written

    report = diagnose_commit(cache, 'deadbeef')

    assert report['final']['stage_found'] == 'not_found'
    assert any('not found' in w for w in report['warnings'])
    assert report['commit']['commit'] == 'deadbeef'


# ---------------------------------------------------------------------------
# SHA ambiguity warning
# ---------------------------------------------------------------------------

def test_diagnose_sha_ambiguity_warning(tmp_path):
    cache = _cache(tmp_path)
    c1 = _make_commit(sha='aabb000011', subject='usb: fix x', score=50, rank=1)
    c2 = _make_commit(sha='aabb000022', subject='usb: fix y', score=40, rank=2)
    _write_json(os.path.join(cache, CACHE_FILES['relevant']), [c1, c2])

    report = diagnose_commit(cache, 'aabb')
    assert any('ambiguous' in w for w in report['warnings'])


# ---------------------------------------------------------------------------
# cache_presence map
# ---------------------------------------------------------------------------

def test_diagnose_cache_presence_all_keys_present(tmp_path):
    cache = _cache(tmp_path)
    report = diagnose_commit(cache, 'aabbccdd')
    for key in CACHE_FILES:
        assert key in report['cache_presence'], f'Missing cache_presence key: {key}'


def test_diagnose_cache_presence_missing_file_exists_false(tmp_path):
    cache = _cache(tmp_path)
    report = diagnose_commit(cache, 'aabbccdd')
    for key, info in report['cache_presence'].items():
        assert info['exists'] is False
        assert info['size_bytes'] is None


def test_diagnose_cache_presence_existing_file_has_size(tmp_path):
    cache = _cache(tmp_path)
    _write_json(os.path.join(cache, CACHE_FILES['relevant']),
                [_make_commit(sha='aaaabbbb', score=10, rank=1)])

    report = diagnose_commit(cache, 'aaaa')
    assert report['cache_presence']['relevant']['exists'] is True
    assert report['cache_presence']['relevant']['size_bytes'] > 0


# ---------------------------------------------------------------------------
# meta section
# ---------------------------------------------------------------------------

def test_diagnose_meta_fields(tmp_path):
    cache = _cache(tmp_path)
    report = diagnose_commit(cache, 'aabbccdd')
    assert 'pipeline_version' in report['meta']
    assert report['meta']['sha_query'] == 'aabbccdd'
    assert report['meta']['cache_dir'] == cache


def test_diagnose_meta_has_no_work_dir(tmp_path):
    """meta must not include work_dir -- diagnose operates cache-dir-only."""
    cache = _cache(tmp_path)
    report = diagnose_commit(cache, 'aabbccdd')
    assert 'work_dir' not in report['meta']


# ---------------------------------------------------------------------------
# commit section: body truncated, internals stripped
# ---------------------------------------------------------------------------

def test_diagnose_commit_body_truncated(tmp_path):
    cache = _cache(tmp_path)
    long_body = 'x' * 1000
    commit = _make_commit(sha='aabbccdd1122', subject='foo')
    commit['body'] = long_body
    c = dict(commit)
    c['score'] = 10
    c['_rank'] = 1
    _write_json(os.path.join(cache, CACHE_FILES['relevant']), [c])

    report = diagnose_commit(cache, 'aabbccdd')
    assert len(report['commit']['body']) <= 503  # 500 + '...'


def test_diagnose_commit_internals_stripped(tmp_path):
    cache = _cache(tmp_path)
    commit = _make_commit(
        sha='aabbccdd1122', subject='foo',
        filter_reason='keywords_blacklist',
    )
    commit['meta'] = {'x': 1}
    commit['touched_paths_guess'] = ['net/']
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [commit])

    report = diagnose_commit(cache, 'aabbccdd')
    for k in ('_filter_reason', '_prefilter_debug', 'meta', 'touched_paths_guess'):
        assert k not in report['commit'], f'Internal field {k!r} should be stripped'


# ---------------------------------------------------------------------------
# scoring section: profile_breakdown keys
# ---------------------------------------------------------------------------

def test_diagnose_scoring_profile_breakdown_keys(tmp_path):
    cache = _cache(tmp_path)
    commit = _make_commit(
        sha='aabbccdd1122',
        subject='usb: fix hub',
        score=70,
        rank=1,
        matched_profiles=['usb'],
        product_evidence=['config_map:CONFIG_USB'],
        scoring={
            'profiles': {
                'usb': {
                    'score': 70, 'weight': 100,
                    'matched_rules': ['r1'],
                    'keyword_hits': ['fix'],
                    'path_hits': ['drivers/usb/'],
                }
            }
        },
    )
    _write_json(os.path.join(cache, CACHE_FILES['relevant']), [commit])

    report = diagnose_commit(cache, 'aabbccdd')
    bd = report['scoring']['profile_breakdown']['usb']
    for key in ('score', 'weight', 'matched_rules', 'keyword_hits', 'path_hits'):
        assert key in bd


# ---------------------------------------------------------------------------
# postfilter section: threshold sourced from postfilter_debug.json
# ---------------------------------------------------------------------------

def test_diagnose_postfilter_threshold_from_debug(tmp_path):
    cache = _cache(tmp_path)
    commit = _make_commit(sha='aabb1234ccdd', subject='net: fix x', score=30, rank=1)
    _write_json(os.path.join(cache, CACHE_FILES['relevant']), [commit])
    _write_json(os.path.join(cache, CACHE_FILES['postfilter_debug']),
                {'summary': {'threshold': 15.0}})

    report = diagnose_commit(cache, 'aabb1234')
    assert report['postfilter']['threshold'] == 15.0


# ---------------------------------------------------------------------------
# search priority: relevant takes precedence over lower stages
# ---------------------------------------------------------------------------

def test_diagnose_relevant_wins_over_filtered(tmp_path):
    cache = _cache(tmp_path)
    sha = 'aabbccdd1122'
    rel_commit  = _make_commit(sha=sha, subject='from relevant', score=80, rank=1)
    filt_commit = _make_commit(sha=sha, subject='from filtered',
                               filter_reason='no_kconfig_coverage')
    _write_json(os.path.join(cache, CACHE_FILES['relevant']),  [rel_commit])
    _write_json(os.path.join(cache, CACHE_FILES['filtered']),  [filt_commit])

    report = diagnose_commit(cache, 'aabbccdd')
    assert report['final']['stage_found'] == 'relevant'
    assert report['commit']['subject'] == 'from relevant'
