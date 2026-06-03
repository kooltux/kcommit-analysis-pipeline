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


# ── B: update_stage_progress call-signature regression (A.3 fix) ───────────

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
    monkeypatch.setattr(_mod, '_rt_progress_for_test', cap, raising=False)

    # Directly exercise the inner helper by reconstructing it with a
    # monkeypatched _rt_progress.  We replace the module-level import
    # reference used inside run() by patching at import time via a
    # controlled wrapper.
    #
    # Strategy: run() with a minimal setup so it reaches _update_stage7_progress,
    # but replace lib.pipeline_runtime.update_stage_progress before run() imports it.
    import lib.pipeline_runtime as _rt_mod
    monkeypatch.setattr(_rt_mod, 'update_stage_progress', cap)

    cache, outdir, cfg = _setup(tmp_path)
    run(cfg, cache, outdir)

    assert cap.calls, 'update_stage_progress was never called'

    for call in cap.calls:
        args   = call['args']
        kwargs = call['kwargs']

        # B.1 — first positional arg must be stage index 7
        assert args[0] == 7, (
            f'Expected stage index 7, got {args[0]!r} in call {call}')

        # B.2 — second positional arg must be total stages 7
        assert args[1] == 7, (
            f'Expected stage_total 7, got {args[1]!r} in call {call}')

        # B.3 — third positional arg must be a float fraction in [0.0, 1.0]
        frac = args[2]
        assert isinstance(frac, float), (
            f'Expected frac to be float, got {type(frac).__name__!r} in call {call}')
        assert 0.0 <= frac <= 1.0, (
            f'frac={frac!r} outside [0.0, 1.0] in call {call}')

        # B.4 — fourth positional arg must be a non-empty string label
        label = args[3]
        assert isinstance(label, str) and label, (
            f'Expected non-empty str label, got {label!r} in call {call}')

        # B.5 — n_done keyword must be present and be an int
        assert 'n_done' in kwargs, (
            f'n_done keyword missing in call {call}')
        assert isinstance(kwargs['n_done'], int), (
            f'n_done must be int, got {type(kwargs["n_done"]).__name__!r}')

        # B.6 — n_total keyword must be present and be an int
        assert 'n_total' in kwargs, (
            f'n_total keyword missing in call {call}')
        assert isinstance(kwargs['n_total'], int), (
            f'n_total must be int, got {type(kwargs["n_total"]).__name__!r}')


def test_update_stage7_progress_frac_monotonically_increases(tmp_path, monkeypatch):
    """B.7 — frac values across successive milestones must be non-decreasing."""
    import lib.pipeline_runtime as _rt_mod
    from lib.stages.st07_report import _STAGE7_MILESTONES

    cap = _ProgressCapture()
    monkeypatch.setattr(_rt_mod, 'update_stage_progress', cap)

    cache, outdir, cfg = _setup(tmp_path)
    run(cfg, cache, outdir)

    fracs = [c['args'][2] for c in cap.calls]
    assert fracs, 'No progress calls recorded'
    for i in range(1, len(fracs)):
        assert fracs[i] >= fracs[i - 1], (
            f'frac decreased from {fracs[i-1]} to {fracs[i]} at step {i}')


def test_update_stage7_progress_final_frac_is_one(tmp_path, monkeypatch):
    """B.8 — the last milestone call must emit frac == 1.0 (Done)."""
    import lib.pipeline_runtime as _rt_mod

    cap = _ProgressCapture()
    monkeypatch.setattr(_rt_mod, 'update_stage_progress', cap)

    cache, outdir, cfg = _setup(tmp_path)
    run(cfg, cache, outdir)

    assert cap.calls, 'No progress calls recorded'
    last_frac = cap.calls[-1]['args'][2]
    assert last_frac == 1.0, (
        f'Expected final frac == 1.0, got {last_frac!r}')


def test_update_stage7_progress_survives_rt_progress_exception(tmp_path, monkeypatch):
    """B.9 — if _rt_progress raises, run() must still complete successfully
    and write its outputs (graceful degradation guard added in A.3)."""
    import lib.pipeline_runtime as _rt_mod

    def _boom(*a, **kw):
        raise RuntimeError('simulated TTY error')

    monkeypatch.setattr(_rt_mod, 'update_stage_progress', _boom)

    cache, outdir, cfg = _setup(tmp_path)
    # Must not raise
    stats = run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'relevant_commits.json'))
    assert 'generated_files' in stats


# ══ A.1 (v12.0.3): prefilter_debug.json export + rule_trace.csv ═════════════════════

def test_prefilter_debug_json_copied_to_outdir_when_present(tmp_path):
    """A.1 — when cache/prefilter_debug.json exists, run() copies it to outdir."""
    cache, outdir, cfg = _setup(tmp_path)
    debug_records = [
        {'sha': 'aabbccdd', 'drop_reason': 'path_blacklist_all',
         'subject': 'docs: update readme', 'files': ['Documentation/foo.rst'],
         'debug': {}}
    ]
    _write_json(os.path.join(cache, CACHE_FILES['prefilter_debug']), debug_records)
    run(cfg, cache, outdir)
    out_path = os.path.join(outdir, 'prefilter_debug.json')
    assert os.path.exists(out_path), 'prefilter_debug.json was not copied to outdir'
    data = json.load(open(out_path))
    assert data == debug_records


def test_prefilter_debug_json_in_generated_files_when_present(tmp_path):
    """A.1 — prefilter_debug.json must appear in report_stats['generated_files']."""
    cache, outdir, cfg = _setup(tmp_path)
    _write_json(os.path.join(cache, CACHE_FILES['prefilter_debug']), [{'sha': 'x'}])
    stats = run(cfg, cache, outdir)
    assert any('prefilter_debug' in f for f in stats['generated_files']), (
        f"prefilter_debug.json not in generated_files: {stats['generated_files']}")


def test_prefilter_debug_json_not_created_when_cache_absent(tmp_path):
    """A.1 — when cache/prefilter_debug.json does not exist, outdir must not
    contain the file (no empty placeholder created)."""
    cache, outdir, cfg = _setup(tmp_path)
    # Confirm the cache file is absent
    assert not os.path.exists(os.path.join(cache, CACHE_FILES['prefilter_debug']))
    run(cfg, cache, outdir)
    assert not os.path.exists(os.path.join(outdir, 'prefilter_debug.json')), (
        'prefilter_debug.json must not be created when absent from cache')


def test_rule_trace_csv_written_when_csv_output_enabled(tmp_path):
    """A.1 — rule_trace.csv must be written alongside rule_trace.json when
    CSV is in the outputs list."""
    cache, outdir, cfg = _setup(tmp_path)
    assert 'csv' in cfg['reports']['outputs']
    run(cfg, cache, outdir)
    csv_path = os.path.join(outdir, 'rule_trace.csv')
    assert os.path.exists(csv_path), 'rule_trace.csv was not written'


def test_rule_trace_csv_has_expected_headers(tmp_path):
    """A.1 — rule_trace.csv first row must be the canonical TRACE_COLS header."""
    from lib.stages.st07_report import TRACE_COLS
    cache, outdir, cfg = _setup(tmp_path)
    run(cfg, cache, outdir)
    with open(os.path.join(outdir, 'rule_trace.csv')) as f:
        reader = csv.reader(f)
        headers = next(reader)
    assert headers == list(TRACE_COLS)


def test_rule_trace_csv_in_generated_files(tmp_path):
    """A.1 — rule_trace.csv must appear in report_stats['generated_files']."""
    cache, outdir, cfg = _setup(tmp_path)
    stats = run(cfg, cache, outdir)
    assert any('rule_trace.csv' in f for f in stats['generated_files']), (
        f"rule_trace.csv not in generated_files: {stats['generated_files']}")


def test_rule_trace_csv_not_written_when_csv_disabled(tmp_path):
    """A.1 — rule_trace.csv must NOT be written when CSV output is not enabled."""
    cache, outdir, cfg = _setup(tmp_path)
    cfg['reports']['outputs'] = ['html']
    run(cfg, cache, outdir)
    assert not os.path.exists(os.path.join(outdir, 'rule_trace.csv')), (
        'rule_trace.csv must not be written when CSV output is disabled')


def test_rule_trace_json_always_written(tmp_path):
    """A.1 — rule_trace.json (JSON twin) is always written regardless of outputs."""
    cache, outdir, cfg = _setup(tmp_path)
    cfg['reports']['outputs'] = []  # no CSV, no HTML
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'rule_trace.json')), (
        'rule_trace.json must always be written')


def test_manifest_cache_files_has_prefilter_debug_key():
    """A.1 — CACHE_FILES['prefilter_debug'] must be defined in manifest."""
    from lib.manifest import CACHE_FILES
    assert 'prefilter_debug' in CACHE_FILES, (
        "CACHE_FILES missing 'prefilter_debug' key")
    assert CACHE_FILES['prefilter_debug'].endswith('.json')


def test_manifest_stage4_outputs_include_prefilter_debug():
    """A.1 — MANIFEST.json stage 4 outputs must list prefilter_debug.json."""
    from lib.manifest import STAGE_OUTPUTS
    outputs = STAGE_OUTPUTS.get('prefilter_commits', [])
    assert any('prefilter_debug' in o for o in outputs), (
        f'prefilter_debug.json missing from stage 4 MANIFEST outputs: {outputs}')
