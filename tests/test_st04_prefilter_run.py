"""Tests for lib.stages.st04_prefilter.run() — the stage entry point."""
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


def test_run_writes_filtered_cache(tmp_path):
    cache, cfg = _setup(tmp_path, commits=[_commit('a')])
    run(cfg, cache)
    path = os.path.join(cache, CACHE_FILES['filtered'])
    assert os.path.exists(path)


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
    # Inject path_blacklist into the compiled_rules merged section
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
