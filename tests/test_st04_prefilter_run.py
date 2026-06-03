"""Tests for lib.stages.st04_prefilter.run() — the stage entry point.

v12.0.0 (A.1):
  run() now also writes CACHE_FILES['prefilter_debug'] (prefilter_debug.json)
  with a 'summary' block and a 'dropped' list.  Each entry is built by
  _build_prefilter_debug_entry() and carries per-level filter debug info.
"""
import json, os
import pytest

from lib.stages.st04_prefilter import run
from lib.manifest import CACHE_FILES


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f)


def _read(path):
    with open(path) as f:
        return json.load(f)


def _commit(sha='abc', subject='net: fix skb', files=None):
    return {
        'commit': sha, 'subject': subject, 'body': '',
        'author_name': 'Dev', 'author_time': 0,
        'files': files or ['drivers/net/core.c'],
    }


def _minimal_compiled_rules():
    return {
        'schema_hash': 'test-hash',
        'rules': {},
        'profiles': {
            'networking': {
                'description': '',
                'rules': {},
                'merged': {
                    'keywords_whitelist': ['net:', 'skb'],
                    'keywords_blacklist': [],
                    'path_whitelist':     ['drivers/net/'],
                    'path_blacklist':     [],
                    'commit_whitelist':   [],
                    'commit_blacklist':   [],
                },
            }
        }
    }


def _setup(tmp_path, commits=None, filter_cfg=None):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    _write(os.path.join(cache, CACHE_FILES['commits']),
           commits if commits is not None else [_commit()])
    _write(os.path.join(cache, CACHE_FILES['product_map']), {})
    _write(os.path.join(cache, CACHE_FILES['compiled_rules']),
           _minimal_compiled_rules())
    cfg = {
        'filter': filter_cfg or {},
        'paths': {
            'work_dir':  str(tmp_path),
            'cache_dir': cache,
            'scoring_dir': str(tmp_path / 'scoring'),
        },
        'profiles': {'active': {'networking': 100}},
        'collect': {},
    }
    return cache, cfg


def test_run_returns_kept_and_dropped(tmp_path):
    cache, cfg = _setup(tmp_path, commits=[_commit('a'), _commit('b')])
    kept, dropped, reasons = run(cfg, cache)
    assert len(kept) + len(dropped) == 2


def test_run_writes_filtered_cache(tmp_path):
    """st04.run() saves dropped commits to CACHE_FILES['filtered']; kept is in-memory only."""
    cache, cfg = _setup(tmp_path, commits=[_commit('a')])
    kept, dropped, _ = run(cfg, cache)
    assert os.path.exists(os.path.join(cache, CACHE_FILES['filtered']))
    assert isinstance(kept, list)


def test_run_empty_commits(tmp_path):
    cache, cfg = _setup(tmp_path, commits=[])
    kept, dropped, reasons = run(cfg, cache)
    assert kept == []
    assert dropped == []


def test_run_path_blacklist_drops(tmp_path):
    """Commits where ALL files match the profile path_blacklist are dropped."""
    sha = 'deadbeef'
    commits = [_commit(sha, files=['Documentation/foo.rst', 'Documentation/bar.rst'])]
    cache, cfg = _setup(tmp_path, commits=commits)
    import json
    cr_path = os.path.join(str(tmp_path / 'cache'), CACHE_FILES['compiled_rules'])
    cr = json.load(open(cr_path))
    cr['profiles']['networking']['merged']['path_blacklist'] = ['Documentation/']
    json.dump(cr, open(cr_path, 'w'))
    kept, dropped, _ = run(cfg, cache)
    assert all(c['commit'] != sha for c in kept)
    assert any(c['commit'] == sha for c in dropped)


def test_run_filter_disabled_keeps_all(tmp_path):
    commits = [_commit('a', files=['Documentation/foo.rst'])]
    cache, cfg = _setup(tmp_path, commits=commits,
                        filter_cfg={'enabled': False})
    kept, dropped, _ = run(cfg, cache)
    assert len(kept) == 1
    assert len(dropped) == 0


def test_run_reason_dict_populated(tmp_path):
    """Reasons dict is populated when commits are dropped."""
    import json
    commits = [_commit('doc1', files=['Documentation/a.rst', 'Documentation/b.rst']),
               _commit('good')]
    cache, cfg = _setup(tmp_path, commits=commits)
    cr_path = os.path.join(str(tmp_path / 'cache'), CACHE_FILES['compiled_rules'])
    cr = json.load(open(cr_path))
    cr['profiles']['networking']['merged']['path_blacklist'] = ['Documentation/']
    json.dump(cr, open(cr_path, 'w'))
    _, _, reasons = run(cfg, cache)
    assert isinstance(reasons, dict)
    assert sum(reasons.values()) >= 1


def test_run_writes_kept_and_filtered_caches(tmp_path, monkeypatch):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    commits = [
        {'commit': 'keep1', 'subject': 'net: keep', 'body': '', 'files': ['drivers/net/x.c'], 'author_name': 'A', 'author_time': 0},
        {'commit': 'drop1', 'subject': 'misc', 'body': '', 'files': ['Documentation/readme'], 'author_name': 'A', 'author_time': 0},
    ]
    with open(os.path.join(cache, CACHE_FILES['commits']), 'w') as f:
        json.dump(commits, f)
    with open(os.path.join(cache, CACHE_FILES['product_map']), 'w') as f:
        json.dump({}, f)

    monkeypatch.setattr('lib.stages.st04_prefilter.load_profile_rules', lambda cfg: {
        'p': {'merged': {'commit_whitelist': [], 'commit_blacklist': [],
                         'path_whitelist': ['drivers/net/*'], 'path_blacklist': ['Documentation/*'],
                         'keywords_whitelist': [], 'keywords_blacklist': []},
              'rules': {}}
    })
    monkeypatch.setattr('lib.stages.st04_prefilter.precompile_rules', lambda rules: None)
    monkeypatch.setattr('lib.stages.st04_prefilter.extract_commit_meta', lambda c: {})
    monkeypatch.setattr('lib.stages.st04_prefilter.infer_touched_paths', lambda subject, cfg: [])

    kept, dropped, _ = run({'filter': {}}, cache)
    with open(os.path.join(cache, CACHE_FILES['prefilter_kept'])) as f:
        kept_cache = json.load(f)
    with open(os.path.join(cache, CACHE_FILES['filtered'])) as f:
        dropped_cache = json.load(f)

    assert [c['commit'] for c in kept] == ['keep1']
    assert [c['commit'] for c in dropped] == ['drop1']
    assert [c['commit'] for c in kept_cache] == ['keep1']
    assert [c['commit'] for c in dropped_cache] == ['drop1']


# ══ A.1: prefilter_debug.json tests ══════════════════════════════════════

def test_run_writes_prefilter_debug_json(tmp_path):
    """run() writes CACHE_FILES['prefilter_debug'] after each run."""
    cache, cfg = _setup(tmp_path, commits=[_commit('abc')])
    run(cfg, cache)
    dbg_path = os.path.join(cache, CACHE_FILES['prefilter_debug'])
    assert os.path.exists(dbg_path), 'prefilter_debug.json must be written by run()'


def test_run_prefilter_debug_has_summary_block(tmp_path):
    cache, cfg = _setup(tmp_path, commits=[_commit('abc'), _commit('xyz')])
    run(cfg, cache)
    dbg = _read(os.path.join(cache, CACHE_FILES['prefilter_debug']))
    assert 'summary' in dbg
    s = dbg['summary']
    for key in ('total_commits', 'kept', 'dropped', 'drop_reasons'):
        assert key in s, f'summary missing key: {key!r}'
    assert s['total_commits'] == 2


def test_run_prefilter_debug_has_dropped_list(tmp_path):
    cache, cfg = _setup(tmp_path, commits=[_commit('abc')])
    run(cfg, cache)
    dbg = _read(os.path.join(cache, CACHE_FILES['prefilter_debug']))
    assert 'dropped' in dbg
    assert isinstance(dbg['dropped'], list)


def test_run_prefilter_debug_dropped_entry_has_required_keys(tmp_path):
    """Each entry in 'dropped' list has sha, sha12, subject, author, files, drop_reason, debug."""
    import json
    sha = 'cafebabe'
    commits = [_commit(sha, files=['Documentation/a.rst', 'Documentation/b.rst'])]
    cache, cfg = _setup(tmp_path, commits=commits)
    cr_path = os.path.join(str(tmp_path / 'cache'), CACHE_FILES['compiled_rules'])
    cr = json.load(open(cr_path))
    cr['profiles']['networking']['merged']['path_blacklist'] = ['Documentation/']
    json.dump(cr, open(cr_path, 'w'))
    run(cfg, cache)
    dbg = _read(os.path.join(cache, CACHE_FILES['prefilter_debug']))
    assert len(dbg['dropped']) == 1
    entry = dbg['dropped'][0]
    for key in ('sha', 'sha12', 'subject', 'author', 'files', 'drop_reason', 'debug'):
        assert key in entry, f'dropped entry missing key: {key!r}'
    assert entry['sha'] == sha
    assert entry['sha12'] == sha[:12]
    assert entry['drop_reason'] in ('path_blacklist_all',)


def test_run_prefilter_debug_debug_block_has_filter_level_keys(tmp_path):
    """The 'debug' sub-dict carries all expected filter-level keys."""
    import json
    commits = [_commit('d00d', files=['Documentation/a.rst', 'Documentation/b.rst'])]
    cache, cfg = _setup(tmp_path, commits=commits)
    cr_path = os.path.join(str(tmp_path / 'cache'), CACHE_FILES['compiled_rules'])
    cr = json.load(open(cr_path))
    cr['profiles']['networking']['merged']['path_blacklist'] = ['Documentation/']
    json.dump(cr, open(cr_path, 'w'))
    run(cfg, cache)
    dbg = _read(os.path.join(cache, CACHE_FILES['prefilter_debug']))
    inner = dbg['dropped'][0]['debug']
    for key in ('sha', 'files', 'filter_enabled', 'kconfig_required',
                'l3_commit_wl_match', 'l3_commit_bl_match',
                'l2a_path_bl_matches', 'l2b_path_wl_matches',
                'l2half_artifact_files',
                'l2half_kconfig_covered_files', 'l2half_kconfig_uncovered_files',
                'l1a_kw_wl_matches', 'l1b_kw_bl_matches'):
        assert key in inner, f'debug block missing key: {key!r}'


def test_run_prefilter_debug_no_dropped_when_all_kept(tmp_path):
    """'dropped' list is empty when no commits are filtered."""
    cache, cfg = _setup(tmp_path, commits=[_commit('abc')])
    run(cfg, cache)
    dbg = _read(os.path.join(cache, CACHE_FILES['prefilter_debug']))
    assert dbg['dropped'] == []
    assert dbg['summary']['dropped'] == 0


def test_run_prefilter_debug_summary_counts_match_actual(tmp_path):
    """summary.kept + summary.dropped == summary.total_commits."""
    import json
    commits = [
        _commit('d1', files=['Documentation/a.rst', 'Documentation/b.rst']),
        _commit('d2', files=['Documentation/c.rst', 'Documentation/d.rst']),
        _commit('k1'),   # kept
    ]
    cache, cfg = _setup(tmp_path, commits=commits)
    cr_path = os.path.join(str(tmp_path / 'cache'), CACHE_FILES['compiled_rules'])
    cr = json.load(open(cr_path))
    cr['profiles']['networking']['merged']['path_blacklist'] = ['Documentation/']
    json.dump(cr, open(cr_path, 'w'))
    run(cfg, cache)
    dbg = _read(os.path.join(cache, CACHE_FILES['prefilter_debug']))
    s = dbg['summary']
    assert s['total_commits'] == 3
    assert s['dropped'] == 2
    assert s['kept'] == 1
    assert s['kept'] + s['dropped'] == s['total_commits']
