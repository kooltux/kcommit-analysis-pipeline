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
    #   top-level: { schema_hash, rules: {rulename: body}, profiles: {pname: {rules:{}}}
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
    assert os.path.exists(os.path.join(outdir, 'summary.html'))


def test_html_filtered_output_written(tmp_path):
    """v16.14.0: filtered commits are embedded in the unified
    summary.html report; no separate filtered_commits.html is written.
    Verify that summary.html is produced when filtered commits exist."""
    flt = [_commit('dropped', reason='commit_blacklist')]
    cache, outdir, cfg = _setup(tmp_path, filtered=flt)
    cfg['reports']['outputs'] = ['html']
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'summary.html'))


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

    cache, outdir, cfg = _setup(tmp_path)
    run(cfg, cache, outdir)

    assert cap.calls, 'No progress calls recorded — _rt_progress_f was never invoked'

    for call in cap.calls:
        args   = call['args']
        kwargs = call['kwargs']
        # B.1 index == 7
        assert args[0] == 7,                  f'B.1 stage index: expected 7, got {args[0]}'
        # B.2 stage_total == 7
        assert args[1] == 7,                  f'B.2 stage_total: expected 7, got {args[1]}'
        # B.3 frac in [0.0, 1.0]
        assert isinstance(args[2], float),    f'B.3 frac not a float: {type(args[2])}'
        assert 0.0 <= args[2] <= 1.0,         f'B.3 frac out of range: {args[2]}'
        # B.4 label is str
        assert isinstance(args[3], str),      f'B.4 label not a str: {type(args[3])}'
        # B.5 n_done is int
        assert isinstance(kwargs['n_done'], int),  f'B.5 n_done not int: {type(kwargs["n_done"])}'
        # B.6 n_total is int
        assert isinstance(kwargs['n_total'], int), f'B.6 n_total not int: {type(kwargs["n_total"])}'


# ── G.4: bucket sidecar layout ──────────────────────────────────────────────────────────────────────

def test_commit_details_bucket_file_written(tmp_path):
    """G.4 — _write_commit_details() must write bucket files at
    commits/<sha[0]>/<sha[1:3]>.json instead of per-commit files.
    The bucket file must be a dict keyed by full SHA."""
    sha = 'abc123def4567890'
    cache, outdir, cfg = _setup(tmp_path, scored=[_commit(sha=sha)])
    run(cfg, cache, outdir)
    bucket_path = os.path.join(outdir, 'commits', sha[0], sha[1:3] + '.json')
    assert os.path.exists(bucket_path), (
        f'Bucket file not found at {bucket_path}'
    )
    data = json.load(open(bucket_path))
    assert sha in data, f'Full SHA {sha!r} not found as key in bucket'
    assert data[sha]['commit'] == sha


def test_commit_details_no_per_sha_file_written(tmp_path):
    """G.4 — old per-commit layout (commits/<sha[0:2]>/<sha[2:4]>/<sha>.json)
    must NOT be written."""
    sha = 'abc123def4567890'
    cache, outdir, cfg = _setup(tmp_path, scored=[_commit(sha=sha)])
    run(cfg, cache, outdir)
    old_path = os.path.join(outdir, 'commits', sha[0:2], sha[2:4], sha + '.json')
    assert not os.path.exists(old_path), (
        f'Old per-SHA file still written at {old_path} — bucket layout not applied'
    )


def test_commit_details_same_bucket_merged(tmp_path):
    """G.4 — two commits sharing bucket prefix <sha[0]>/<sha[1:3]> must
    both appear as keys in the same bucket JSON file."""
    sha1 = 'abc123def4567890'
    sha2 = 'abc999000111aaab'
    cache, outdir, cfg = _setup(
        tmp_path,
        scored=[_commit(sha=sha1, rank=1), _commit(sha=sha2, rank=2)],
    )
    run(cfg, cache, outdir)
    bucket_path = os.path.join(outdir, 'commits', 'a', 'bc.json')
    assert os.path.exists(bucket_path), f'Shared bucket file not found: {bucket_path}'
    data = json.load(open(bucket_path))
    assert sha1 in data, f'{sha1!r} missing from bucket'
    assert sha2 in data, f'{sha2!r} missing from bucket'


def test_commit_details_different_buckets_written_separately(tmp_path):
    """G.4 — commits with different bucket prefixes must produce separate
    bucket files; each bucket contains only its own commits."""
    sha_a = 'abc000000000aaaa'
    sha_b = 'def111111111bbbb'
    cache, outdir, cfg = _setup(
        tmp_path,
        scored=[_commit(sha=sha_a, rank=1), _commit(sha=sha_b, rank=2)],
    )
    run(cfg, cache, outdir)
    bucket_a = os.path.join(outdir, 'commits', 'a', 'bc.json')
    bucket_b = os.path.join(outdir, 'commits', 'd', 'ef.json')
    assert os.path.exists(bucket_a), f'Bucket A not found: {bucket_a}'
    assert os.path.exists(bucket_b), f'Bucket B not found: {bucket_b}'
    data_a = json.load(open(bucket_a))
    data_b = json.load(open(bucket_b))
    assert sha_a in data_a and sha_b not in data_a
    assert sha_b in data_b and sha_a not in data_b
