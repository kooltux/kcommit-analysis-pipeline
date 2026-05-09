"""Tests for lib.stages.st07_report — run(), output file generation."""
import csv, json, os
import pytest

from lib.stages.st07_report import run
from lib.manifest import CACHE_FILES


def _commit(sha='abc123', score=50, rank=1, reason=None):
    c = {
        'commit': sha, 'subject': f'fix: {sha}', 'score': score,
        '_rank': rank, 'author_name': 'Dev', 'author_time': 1700000000,
        'matched_profiles': ['security'], 'product_evidence': ['config_map:CONFIG_USB'],
    }
    if reason:
        c['_filter_reason'] = reason
    return c


def _setup(tmp_path, scored=None, filtered=None, cfg_extra=None):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    scored   = scored   if scored   is not None else [_commit()]
    filtered = filtered if filtered is not None else []
    with open(os.path.join(cache, CACHE_FILES['relevant']), 'w') as f:
        json.dump(scored, f)
    with open(os.path.join(cache, CACHE_FILES['filtered']), 'w') as f:
        json.dump(filtered, f)

    # Write a compiled_rules.json that load_profile_rules() accepts
    # without recompiling (requires a 'schema_hash' sentinel key added in v9.12).
    # Structure mirrors what compile_rules_for_config() produces:
    #   top-level: { schema_hash, rules: {rulename: body}, profiles: {pname: {rules:{}}}}
    _rule_body = {
        'keywords_whitelist': [], 'keywords_blacklist': [],
        'path_whitelist': [],    'path_blacklist': [],
        'commit_whitelist': [],  'commit_blacklist': [],
    }
    compiled_rules = {
        'schema_hash': 'test-sentinel-hash',
        'rules':    {},
        'profiles': {
            'security': {
                'description': 'Security fixes',
                'rules': {},
                'merged': _rule_body,
            }
        },
    }
    with open(os.path.join(cache, CACHE_FILES['compiled_rules']), 'w') as f:
        json.dump(compiled_rules, f)

    cfg = {
        'reports': {'outputs': ['csv'], 'title': 'Test', 'top_n': 0},
        'paths':   {'templates_dir': None, 'cache_dir': cache,
                    'work_dir': str(tmp_path)},
        'profiles': {'active': {'security': 100}},
    }
    if cfg_extra:
        for k, v in cfg_extra.items():
            cfg.setdefault(k, {}).update(v)
    return cache, outdir, cfg


# ── JSON outputs always written ────────────────────────────────────────────
def test_relevant_commits_json_written(tmp_path):
    cache, outdir, cfg = _setup(tmp_path)
    run(cfg, cache, outdir)
    path = os.path.join(outdir, 'relevant_commits.json')
    assert os.path.exists(path)
    data = json.load(open(path))
    assert len(data) == 1
    assert data[0]['commit'] == 'abc123'


def test_profile_summary_json_written(tmp_path):
    cache, outdir, cfg = _setup(tmp_path)
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'profile_summary.json'))


def test_profile_matrix_json_written(tmp_path):
    cache, outdir, cfg = _setup(tmp_path)
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'profile_matrix.json'))


def test_report_stats_json_written(tmp_path):
    cache, outdir, cfg = _setup(tmp_path)
    stats = run(cfg, cache, outdir)
    path = os.path.join(outdir, 'report_stats.json')
    assert os.path.exists(path)
    data = json.load(open(path))
    assert 'generated_files' in data


# ── generated_files tracking ──────────────────────────────────────────────
def test_generated_files_contains_csv(tmp_path):
    cache, outdir, cfg = _setup(tmp_path)
    stats = run(cfg, cache, outdir)
    assert any('relevant_commits.csv' in f for f in stats['generated_files'])


def test_generated_files_not_contains_report_stats(tmp_path):
    """report_stats.json must not list itself in generated_files."""
    cache, outdir, cfg = _setup(tmp_path)
    stats = run(cfg, cache, outdir)
    assert not any('report_stats.json' in f for f in stats['generated_files'])


# ── CSV output ────────────────────────────────────────────────────────────
def test_csv_output_correct_headers(tmp_path):
    from lib.manifest import COMMIT_COLS
    cache, outdir, cfg = _setup(tmp_path)
    run(cfg, cache, outdir)
    with open(os.path.join(outdir, 'relevant_commits.csv')) as f:
        reader = csv.reader(f)
        headers = next(reader)
    assert headers == list(COMMIT_COLS)


def test_csv_output_correct_row_count(tmp_path):
    cache, outdir, cfg = _setup(tmp_path,
                                scored=[_commit('a', rank=1), _commit('b', rank=2)])
    run(cfg, cache, outdir)
    with open(os.path.join(outdir, 'relevant_commits.csv')) as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3  # 1 header + 2 data rows


# ── filtered_commits outputs ──────────────────────────────────────────────
def test_filtered_commits_json_written_when_present(tmp_path):
    flt = [_commit('dropped', reason='path_blacklist')]
    cache, outdir, cfg = _setup(tmp_path, filtered=flt)
    run(cfg, cache, outdir)
    path = os.path.join(outdir, 'filtered_commits.json')
    assert os.path.exists(path)


def test_filtered_commits_csv_has_filter_reason_column(tmp_path):
    from lib.manifest import COMMIT_COLS_FILTERED
    flt = [_commit('dropped', reason='keywords_blacklist')]
    cache, outdir, cfg = _setup(tmp_path, filtered=flt)
    run(cfg, cache, outdir)
    with open(os.path.join(outdir, 'filtered_commits.csv')) as f:
        reader = csv.reader(f)
        headers = next(reader)
    assert headers == list(COMMIT_COLS_FILTERED)


def test_filtered_commits_csv_not_written_when_empty(tmp_path):
    cache, outdir, cfg = _setup(tmp_path, filtered=[])
    run(cfg, cache, outdir)
    assert not os.path.exists(os.path.join(outdir, 'filtered_commits.csv'))


# ── HTML output ───────────────────────────────────────────────────────────
def test_html_output_written(tmp_path):
    cache, outdir, cfg = _setup(tmp_path,
                                cfg_extra={'reports': {'outputs': ['html']}})
    cfg['reports']['outputs'] = ['html']
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'relevant_commits.html'))


def test_html_filtered_output_written(tmp_path):
    flt = [_commit('dropped', reason='commit_blacklist')]
    cache, outdir, cfg = _setup(tmp_path, filtered=flt)
    cfg['reports']['outputs'] = ['html']
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'filtered_commits.html'))


# ── top_n limiting ────────────────────────────────────────────────────────
def test_top_n_limits_output(tmp_path):
    many = [_commit(sha=str(i), score=100-i, rank=i+1) for i in range(10)]
    cache, outdir, cfg = _setup(tmp_path, scored=many)
    cfg['reports']['top_n'] = 3
    run(cfg, cache, outdir)
    data = json.load(open(os.path.join(outdir, 'relevant_commits.json')))
    assert len(data) == 3


def test_top_n_zero_means_no_limit(tmp_path):
    many = [_commit(sha=str(i), score=100-i, rank=i+1) for i in range(10)]
    cache, outdir, cfg = _setup(tmp_path, scored=many)
    cfg['reports']['top_n'] = 0
    run(cfg, cache, outdir)
    data = json.load(open(os.path.join(outdir, 'relevant_commits.json')))
    assert len(data) == 10
