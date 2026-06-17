"""Tests for lib.stages.st07_report — run(), output file generation."""
import csv, json, os
import pytest

from lib.stages.st07_report import run
from lib.manifest import CACHE_FILES


def _commit(sha='abc123', score=50, rank=1, reason=None):
    c = {
        'commit': sha, 'subject': f'fix: {sha}', 'score': score,
        '_rank': rank, 'author_name': 'Dev', 'author_time': 1700000000,
        'matched_profiles': ['security_fixes'], 'product_evidence': ['config_map:CONFIG_USB'],
    }
    if reason:
        c['_filter_reason'] = reason
    return c




def _write_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f)

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
            'security_fixes': {
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
        'profiles': {'active': {'security_fixes': 100}},
    }
    if cfg_extra:
        for k, v in cfg_extra.items():
            cfg.setdefault(k, {}).update(v)
    return cache, outdir, cfg


# ── JSON outputs always written ──────────────────────────────────────────────────────────────────────
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


# ── generated_files tracking ─────────────────────────────────────────────────────────────────────
def test_generated_files_contains_csv(tmp_path):
    cache, outdir, cfg = _setup(tmp_path)
    stats = run(cfg, cache, outdir)
    assert any('relevant_commits.csv' in f for f in stats['generated_files'])


def test_generated_files_not_contains_report_stats(tmp_path):
    """report_stats.json must not list itself in generated_files."""
    cache, outdir, cfg = _setup(tmp_path)
    stats = run(cfg, cache, outdir)
    assert not any('report_stats.json' in f for f in stats['generated_files'])


# ── CSV output ───────────────────────────────────────────────────────────────────────────────────
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


# ── filtered_commits outputs ───────────────────────────────────────────────────────────────────
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


# ── HTML output ───────────────────────────────────────────────────────────────────────────────────
def test_html_output_written(tmp_path):
    cache, outdir, cfg = _setup(tmp_path,
                                cfg_extra={'reports': {'outputs': ['html']}})
    cfg['reports']['outputs'] = ['html']
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'relevant_commits.html'))


def test_html_filtered_output_written(tmp_path):
    """v16.14.0: filtered commits are embedded in the unified
    relevant_commits.html report; no separate filtered_commits.html is written.
    Verify that relevant_commits.html is produced when filtered commits exist."""
    flt = [_commit('dropped', reason='commit_blacklist')]
    cache, outdir, cfg = _setup(tmp_path, filtered=flt)
    cfg['reports']['outputs'] = ['html']
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'relevant_commits.html'))


# ── top_n limiting ──────────────────────────────────────────────────────────────────────────────────
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


def test_filtered_outputs_merge_prefilter_and_postfilter_drops(tmp_path):
    cache, outdir, cfg = _setup(tmp_path)
    _write_json(os.path.join(cache, CACHE_FILES['filtered']), [{
        'commit': 'pre', 'subject': 'prefilter', 'author_name': 'A', 'author_time': 0,
        'files': [], '_filter_reason': 'prefilter'}])
    _write_json(os.path.join(cache, CACHE_FILES['postfilter_dropped']), [{
        'commit': 'post', 'subject': 'postfilter', 'author_name': 'A', 'author_time': 0,
        'score': 1, 'matched_profiles': [], 'product_evidence': [], 'meta': {}, 'scoring': {},
        '_filter_reason': 'score_below_threshold (10)'}])
    run(cfg, cache, outdir)
    with open(os.path.join(outdir, 'filtered_commits.json')) as f:
        data = json.load(f)
    assert [c['commit'] for c in data] == ['pre', 'post']


# ── B: update_stage_progress call-signature regression (A.3 fix) ───────────────────────

class _ProgressCapture:
    """Captures all calls made to the mocked _rt_progress."""
    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append({'args': args, 'kwargs': kwargs})


def test_update_stage7_progress_calls_rt_progress_with_correct_signature(tmp_path, monkeypatch):
    """B — A.3 regression: _update_stage7_progress() must call
    update_stage_progress() with the correct positional and keyword args.

    Expected call shape for milestone (current=3, total=6, message='foo'):
        args   = (7, 7, 0.5, 'foo')
        kwargs = {'n_done': 3, 'n_total': 6}

    Verifies:
      B.1  index     == 7            (this stage's position)
      B.2  stage_total == 7          (total number of stages)
      B.3  frac is float in [0.0, 1.0]
      B.4  label is a str
      B.5  n_done  == current (int)
      B.6  n_total == total   (int)
    """
    import lib.stages.st07_report as _mod

    cap = _ProgressCapture()
    monkeypatch.setattr(_mod, '_rt_progress_f', cap, raising=False)
