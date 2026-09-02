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


# ── v19.3.0: AI analysis chunking support ───────────────────────────────────────────────────────────

def _setup_ai(tmp_path, num_commits=5):
    """Setup for AI analysis tests with specified number of commits."""
    cache = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    
    # Create prefilter_kept commits
    prefilter_kept = [
        {
            'commit': f'{i:040x}',
            'subject': f'fix: commit {i}',
            'author_name': 'Dev',
            'author_email': 'dev@example.com',
            'author_org': 'example',
            'author_time': 1700000000 + i,
            'body': f'Commit body for {i}',
            'files': [f'file{i}.c'],
            'stats': {'files_changed': 1, 'lines_changed': 10, 'hunks': 1},
            'meta': {'is_fix': True, 'has_cve': False, 'has_syzbot': False, 'has_stable_cc': True},
        }
        for i in range(num_commits)
    ]
    
    # Write prefilter_kept and product_map
    with open(os.path.join(cache, CACHE_FILES['prefilter_kept']), 'w') as f:
        json.dump(prefilter_kept, f)
    with open(os.path.join(cache, CACHE_FILES['product_map']), 'w') as f:
        json.dump({}, f)
    
    # Also write other required cache files
    with open(os.path.join(cache, CACHE_FILES['relevant']), 'w') as f:
        json.dump([], f)
    with open(os.path.join(cache, CACHE_FILES['filtered']), 'w') as f:
        json.dump([], f)
    with open(os.path.join(cache, CACHE_FILES['postfilter_dropped']), 'w') as f:
        json.dump([], f)
    with open(os.path.join(cache, CACHE_FILES['scored']), 'w') as f:
        json.dump([], f)
    with open(os.path.join(cache, CACHE_FILES['commits']), 'w') as f:
        json.dump([], f)
    
    # Write compiled_rules.json
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
        'reports': {'outputs': [], 'title': 'Test', 'top_n': 0},
        'paths':   {'templates_dir': None, 'cache_dir': cache,
                    'work_dir': str(tmp_path), 'configdir': str(tmp_path / 'configs')},
        'profiles': {'active': {'security_fixes': 100}},
        'ai': {},
    }
    
    return cache, outdir, cfg


def test_ai_analysis_single_file_default(tmp_path):
    """v19.3.0 — AI analysis with chunk_size=0 (default) writes single file."""
    cache, outdir, cfg = _setup_ai(tmp_path, num_commits=5)
    
    run(cfg, cache, outdir)
    
    # Should write ai_analysis_input.json (single file)
    ai_path = os.path.join(outdir, 'ai_analysis_input.json')
    assert os.path.exists(ai_path), 'ai_analysis_input.json not written'
    
    # Should NOT write ai_analysis_input/ directory
    chunk_dir = os.path.join(outdir, 'ai_analysis_input')
    assert not os.path.exists(chunk_dir), 'ai_analysis_input/ should not exist with chunk_size=0'
    
    # Verify content
    data = json.load(open(ai_path))
    assert 'commits' in data
    assert len(data['commits']) == 5
    assert 'chunk_info' not in data


def test_ai_analysis_chunked_output(tmp_path):
    """v19.3.0 — AI analysis with chunk_size > 0 writes multiple chunk files."""
    cache, outdir, cfg = _setup_ai(tmp_path, num_commits=25)
    cfg['ai']['chunk_size'] = 10  # 25 commits / 10 per chunk = 3 chunks
    
    run(cfg, cache, outdir)
    
    # Should NOT write ai_analysis_input.json (single file)
    ai_path = os.path.join(outdir, 'ai_analysis_input.json')
    assert not os.path.exists(ai_path), 'ai_analysis_input.json should not exist with chunking'
    
    # Should write ai_analysis_input/ directory with chunk files
    chunk_dir = os.path.join(outdir, 'ai_analysis_input')
    assert os.path.exists(chunk_dir), 'ai_analysis_input/ directory not created'
    
    # Should have 3 chunk files: 1.json, 2.json, 3.json
    chunk_files = sorted([f for f in os.listdir(chunk_dir) if f.endswith('.json')])
    assert len(chunk_files) == 3, f'Expected 3 chunks, got {len(chunk_files)}'
    assert chunk_files == ['1.json', '2.json', '3.json']
    
    # Verify chunk content
    for i, chunk_file in enumerate(chunk_files):
        chunk_path = os.path.join(chunk_dir, chunk_file)
        data = json.load(open(chunk_path))
        
        assert 'chunk_info' in data, f'chunk_info missing from {chunk_file}'
        assert data['chunk_info']['chunk_number'] == i + 1
        assert data['chunk_info']['total_chunks'] == 3
        
        if i < 2:  # First two chunks should have 10 commits each
            assert len(data['commits']) == 10
        else:  # Last chunk should have 5 commits
            assert len(data['commits']) == 5


def test_ai_analysis_prompt_copied_to_output(tmp_path):
    """v19.3.0 — AI analysis prompt is copied to output directory."""
    cache, outdir, cfg = _setup_ai(tmp_path, num_commits=5)
    
    # Create a prompt file
    configs_dir = tmp_path / 'configs'
    ai_dir = configs_dir / 'ai'
    ai_dir.mkdir(parents=True)
    prompt_path = ai_dir / 'ai_analysis_prompt.md'
    prompt_path.write_text('# Test Prompt\n\nThis is a test prompt.')
    
    run(cfg, cache, outdir)
    
    # Should copy prompt to output
    output_prompt = os.path.join(outdir, 'ai_analysis_prompt.md')
    assert os.path.exists(output_prompt), 'ai_analysis_prompt.md not copied to output'
    
    content = open(output_prompt).read()
    assert '# Test Prompt' in content


def test_ai_analysis_custom_prompt_path(tmp_path):
    """v19.3.0 — AI analysis respects custom ai.prompt_path config."""
    cache, outdir, cfg = _setup_ai(tmp_path, num_commits=5)
    
    # Create custom prompt location
    custom_prompt = tmp_path / 'custom_prompt.md'
    custom_prompt.write_text('# Custom Prompt\n\nCustom content.')
    cfg['ai']['prompt_path'] = str(custom_prompt)
    
    run(cfg, cache, outdir)
    
    # Should use custom prompt
    output_prompt = os.path.join(outdir, 'ai_analysis_prompt.md')
    assert os.path.exists(output_prompt)
    
    content = open(output_prompt).read()
    assert '# Custom Prompt' in content
    assert 'Custom content' in content


def test_ai_analysis_no_commits(tmp_path):
    """v19.3.0 — AI analysis handles empty prefilter_kept gracefully."""
    cache, outdir, cfg = _setup_ai(tmp_path, num_commits=0)
    
    run(cfg, cache, outdir)
    
    # Should not write any AI files when no commits
    ai_path = os.path.join(outdir, 'ai_analysis_input.json')
    chunk_dir = os.path.join(outdir, 'ai_analysis_input')
    
    assert not os.path.exists(ai_path)
    assert not os.path.exists(chunk_dir)


# ── v19.4.0: cherry-pick execution script generation ─────────────────────────────────────────────

def _seed_cherry_db(cache_dir_root, rev_old, results):
    """Seed a CherryDB for rev_old with sha -> {'ok': bool} results."""
    from lib.cherrypick_db import load_or_create_db
    db = load_or_create_db(cache_dir_root, rev_old)
    for sha, res in results.items():
        db.add_result(sha, res)
    db.save()


def test_cherry_pick_scripts_not_written_when_test_disabled(tmp_path):
    """collect.cherry_pick_test is falsy (default) -- no scripts should appear,
    even if a CherryDB happens to exist."""
    sha = 'abc123def4567890'
    cache, outdir, cfg = _setup(tmp_path, scored=[_commit(sha=sha)])
    cfg['kernel'] = {'source_dir': str(tmp_path / 'src'), 'rev_old': 'v6.1', 'rev_new': 'v6.6'}
    cp_cache_dir = str(tmp_path / 'cpcache')
    cfg['collect'] = {'cherry_pick_cache_dir': cp_cache_dir}
    _seed_cherry_db(cp_cache_dir, 'v6.1', {sha: {'ok': True}})

    stats = run(cfg, cache, outdir)

    assert not os.path.exists(os.path.join(outdir, 'cherry_pick_relevant.sh'))
    assert not os.path.exists(os.path.join(outdir, 'cherry_pick_prefiltered.sh'))
    assert not any('cherry_pick_' in f for f in stats['generated_files'])


def test_cherry_pick_scripts_not_written_when_rev_old_missing(tmp_path):
    """cherry_pick_test enabled but kernel.rev_old absent -- still gated off."""
    sha = 'abc123def4567890'
    cache, outdir, cfg = _setup(tmp_path, scored=[_commit(sha=sha)])
    cfg['kernel'] = {'source_dir': str(tmp_path / 'src')}
    cfg['collect'] = {'cherry_pick_test': True,
                      'cherry_pick_cache_dir': str(tmp_path / 'cpcache')}

    stats = run(cfg, cache, outdir)

    assert not os.path.exists(os.path.join(outdir, 'cherry_pick_relevant.sh'))
    assert not any('cherry_pick_' in f for f in stats['generated_files'])


def test_cherry_pick_relevant_script_written_when_enabled_and_ok(tmp_path):
    from unittest.mock import patch
    sha = 'abc123def4567890'
    cache, outdir, cfg = _setup(tmp_path, scored=[_commit(sha=sha)])
    cfg['kernel'] = {'source_dir': str(tmp_path / 'src'), 'rev_old': 'v6.1', 'rev_new': 'v6.6'}
    cp_cache_dir = str(tmp_path / 'cpcache')
    cfg['collect'] = {'cherry_pick_test': True, 'cherry_pick_cache_dir': cp_cache_dir}
    _seed_cherry_db(cp_cache_dir, 'v6.1', {sha: {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits', return_value=[sha]):
        stats = run(cfg, cache, outdir)

    rel_path = os.path.join(outdir, 'cherry_pick_relevant.sh')
    assert os.path.exists(rel_path)
    with open(rel_path) as f:
        content = f.read()
    # v19.4.2: now uses cp_one() wrapper instead of raw git cherry-pick
    assert 'cp_one "%s"' % sha in content
    assert any('cherry_pick_relevant.sh' in f for f in stats['generated_files'])


def test_cherry_pick_prefiltered_script_uses_prefilter_kept_cache(tmp_path):
    from unittest.mock import patch
    from lib.manifest import CACHE_FILES
    sha_relevant = 'a1' * 20
    sha_extra     = 'b2' * 20
    cache, outdir, cfg = _setup(tmp_path, scored=[_commit(sha=sha_relevant)])
    _write_json(os.path.join(cache, CACHE_FILES['prefilter_kept']),
               [{'commit': sha_relevant, 'subject': 'x'}, {'commit': sha_extra, 'subject': 'y'}])
    cfg['kernel'] = {'source_dir': str(tmp_path / 'src'), 'rev_old': 'v6.1', 'rev_new': 'v6.6'}
    cp_cache_dir = str(tmp_path / 'cpcache')
    cfg['collect'] = {'cherry_pick_test': True, 'cherry_pick_cache_dir': cp_cache_dir}
    _seed_cherry_db(cp_cache_dir, 'v6.1', {sha_relevant: {'ok': True}, sha_extra: {'ok': True}})

    with patch('lib.cherrypick_script_gen.list_rev_commits',
              return_value=[sha_extra, sha_relevant]):
        stats = run(cfg, cache, outdir)

    pf_path = os.path.join(outdir, 'cherry_pick_prefiltered.sh')
    rel_path = os.path.join(outdir, 'cherry_pick_relevant.sh')
    assert os.path.exists(pf_path)
    assert os.path.exists(rel_path)
    pf_content = open(pf_path).read()
    rel_content = open(rel_path).read()
    assert sha_extra in pf_content       # prefiltered set includes the extra commit
    assert sha_extra not in rel_content  # relevant set does not


def test_cherry_pick_script_generation_failure_is_non_fatal(tmp_path):
    """Even if script generation raises, the report stage must still succeed."""
    from unittest.mock import patch
    sha = 'abc123def4567890'
    cache, outdir, cfg = _setup(tmp_path, scored=[_commit(sha=sha)])
    cfg['kernel'] = {'source_dir': str(tmp_path / 'src'), 'rev_old': 'v6.1', 'rev_new': 'v6.6'}
    cp_cache_dir = str(tmp_path / 'cpcache')
    cfg['collect'] = {'cherry_pick_test': True, 'cherry_pick_cache_dir': cp_cache_dir}
    _seed_cherry_db(cp_cache_dir, 'v6.1', {sha: {'ok': True}})

    with patch('lib.cherrypick_script_gen.write_cherry_pick_script',
              side_effect=RuntimeError('boom')):
        stats = run(cfg, cache, outdir)  # must not raise

    assert 'total_scored_commits' in stats
    assert not os.path.exists(os.path.join(outdir, 'cherry_pick_relevant.sh'))


def test_cherry_pick_relevant_script_completes_quickly_for_large_set(tmp_path):
    """v19.4.1 regression guard at the stage-integration level: report_commits
    must not appear to hang when cherry_pick_test is enabled and the relevant
    set is large.  Exercises the real _write_cherry_pick_scripts() path
    end-to-end (not just the unit-level cherrypick_script_gen tests)."""
    import time
    from unittest.mock import patch
    n = 500
    many = [_commit(sha='s%04d' % i, rank=i + 1) for i in range(n)]
    cache, outdir, cfg = _setup(tmp_path, scored=many)
    cfg['kernel'] = {'source_dir': str(tmp_path / 'src'), 'rev_old': 'v6.1', 'rev_new': 'v6.6'}
    cp_cache_dir = str(tmp_path / 'cpcache')
    cfg['collect'] = {'cherry_pick_test': True, 'cherry_pick_cache_dir': cp_cache_dir}
    _seed_cherry_db(cp_cache_dir, 'v6.1', {c['commit']: {'ok': True} for c in many})

    with patch('lib.cherrypick_script_gen.list_rev_commits',
              return_value=[c['commit'] for c in many]):
        t0 = time.time()
        stats = run(cfg, cache, outdir)
        elapsed = time.time() - t0

    assert os.path.exists(os.path.join(outdir, 'cherry_pick_relevant.sh'))
    assert elapsed < 10.0, (
        'st07_report.run() took %.2fs with cherry_pick_test enabled for %d '
        'relevant commits -- possible regression of the O(N^2) file-read bug '
        'in lib/cherrypick_script_gen.py' % (elapsed, n)
    )
