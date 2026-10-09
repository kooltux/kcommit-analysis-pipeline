"""Tests for lib.stages.st05_score — score_all, _score_serial, run()."""
import json, os
import pytest

from lib.stages.st05_score import score_all, run
from lib.manifest import CACHE_FILES


def _commit(sha='abc', subject='net: fix skb'):
    return {
        'commit': sha, 'subject': subject, 'body': '',
        'author_name': 'Dev', 'author_time': 0,
        'files': ['drivers/net/core.c'],
        'meta': {'has_cve': False, 'is_fix': False,
                 'has_stable_cc': False, 'has_syzbot': False},
        'touched_paths_guess': [],
    }


def _profile_rules():
    return {
        'networking': {
            'description': '',
            'rules': {
                'net_kw': {
                    'keywords_whitelist': ['net:', 'skb'],
                    'keywords_blacklist': [],
                    'path_whitelist':     [],
                    'path_blacklist':     [],
                    'commit_whitelist':   [],
                    'commit_blacklist':   [],
                    'weight':             20,
                }
            },
            'merged': {
                'keywords_whitelist': ['net:', 'skb'],
                'keywords_blacklist': [],
                'path_whitelist':     [],
                'path_blacklist':     [],
                'commit_whitelist':   [],
                'commit_blacklist':   [],
            },
        }
    }


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f)


def _read(path):
    with open(path) as f:
        return json.load(f)


def _compile_fixture_rules(tmp_path, cfg):
    """Use real networking sources and the production compiler/cache contract."""
    profiles = tmp_path / 'profiles'
    rules = tmp_path / 'rules'
    profiles.mkdir()
    (rules / 'net_kw').mkdir(parents=True)
    (profiles / 'networking.json').write_text(
        json.dumps({'rules': {'net_kw': {'weight': 20}}}), encoding='utf-8')
    (rules / 'net_kw' / 'keywords_whitelist.txt').write_text('net:\nskb\n', encoding='utf-8')
    cfg['paths']['profiles_dirs'] = [str(profiles)]
    cfg['paths']['rules_dirs'] = [str(rules)]
    cfg['_meta'] = {'initial_config_dir': str(tmp_path)}
    from lib.profile_rules import compile_rules_for_config
    compile_rules_for_config(cfg, cache_dir=cfg['paths']['cache_dir'])


# ── score_all ─────────────────────────────────────────────────────────────────
def test_score_all_serial_hit():
    """score_all (serial path) scores a matching commit positively."""
    commits = [_commit('a', 'net: fix skb leak')]
    pr = _profile_rules()
    results = score_all(commits, {}, pr, {})
    assert results[0]['score'] > 0


def test_score_all_serial_miss():
    commits = [_commit('b', 'mm: fix page fault')]
    pr = _profile_rules()
    results = score_all(commits, {}, pr, {})
    assert 'networking' not in results[0]['matched_profiles']


def test_score_all_empty():
    results = score_all([], {}, {}, {})
    assert results == []


def test_score_all_forces_serial_when_few_commits():
    """< 100 commits always uses serial path regardless of workers."""
    commits = [_commit(str(i)) for i in range(5)]
    cfg = {'collect': {'score_workers': 4}}
    pr = _profile_rules()
    results = score_all(commits, {}, pr, cfg)
    assert len(results) == 5


# ── run() stage entry point ───────────────────────────────────────────────────
def _setup(tmp_path, commits=None):
    cache = str(tmp_path / 'cache')
    os.makedirs(cache)
    commits = commits if commits is not None else [_commit('x', 'net: fix skb')]
    _write(os.path.join(cache, CACHE_FILES['prefilter_kept']), commits)
    _write(os.path.join(cache, CACHE_FILES['product_map']), {})
    cfg = {
        'paths': {'work_dir': str(tmp_path), 'cache_dir': cache},
        'profiles': {'active': {'networking': 100}},
        'collect': {},
    }
    _compile_fixture_rules(tmp_path, cfg)
    return cache, cfg


def test_run_writes_scored_cache(tmp_path):
    cache, cfg = _setup(tmp_path)
    run(cfg, cache)
    data = _read(os.path.join(cache, CACHE_FILES['scored']))
    assert isinstance(data, list)
    assert len(data) == 1


def test_run_scored_has_score_key(tmp_path):
    cache, cfg = _setup(tmp_path)
    run(cfg, cache)
    data = _read(os.path.join(cache, CACHE_FILES['scored']))
    assert 'score' in data[0]


def test_run_empty_commits(tmp_path):
    cache, cfg = _setup(tmp_path, commits=[])
    run(cfg, cache)
    data = _read(os.path.join(cache, CACHE_FILES['scored']))
    assert data == []


def test_scoring_fixture_has_valid_cache_and_original_network_rule(tmp_path):
    from lib.profile_rules import _current_schema_hash, load_profile_rules
    cache, cfg = _setup(tmp_path)
    document = _read(os.path.join(cache, CACHE_FILES['compiled_rules']))
    assert document['schema_hash'] == _current_schema_hash(cfg)
    rule = load_profile_rules(cfg)['networking']['rules']['net_kw']
    assert rule['weight'] == 20
    assert rule['keywords_whitelist'] == ['net:', 'skb']
    run(cfg, cache)
    assert _read(os.path.join(cache, CACHE_FILES['scored']))[0]['score'] > 0
