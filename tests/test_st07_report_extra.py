"""Extra tests for lib.stages.st07_report — XLSX/ODS output, _fmt_date,
_profile_summary, _commit_rows."""
import csv, json, os
import pytest

from lib.stages.st07_report import run, _fmt_date, _commit_rows
from lib.manifest import CACHE_FILES


def _commit(sha='abc', score=50, rank=1, profiles=None):
    return {
        'commit': sha, 'subject': f'fix: {sha}', 'score': score,
        '_rank': rank, 'author_name': 'Dev', 'author_time': 1700000000,
        'matched_profiles': profiles or ['security_fixes'],
        'product_evidence': ['config_map:CONFIG_USB'],
    }


def _compiled_rules():
    return {
        'schema_hash': 'test',
        'rules': {},
        'profiles': {
            'security_fixes': {'description': 'Security', 'rules': {},
                         'merged': {'keywords_whitelist': [],
                                     'keywords_blacklist': [],
                                     'path_whitelist': [],
                                     'path_blacklist': [],
                                     'commit_whitelist': [],
                                     'commit_blacklist': []}},
        }
    }


def _setup(tmp_path, scored=None, filtered=None, outputs=None):
    cache  = str(tmp_path / 'cache')
    outdir = str(tmp_path / 'output')
    os.makedirs(cache)
    scored   = scored   if scored   is not None else [_commit()]
    filtered = filtered if filtered is not None else []
    with open(os.path.join(cache, CACHE_FILES['relevant']), 'w') as f:
        json.dump(scored, f)
    with open(os.path.join(cache, CACHE_FILES['filtered']), 'w') as f:
        json.dump(filtered, f)
    with open(os.path.join(cache, CACHE_FILES['compiled_rules']), 'w') as f:
        json.dump(_compiled_rules(), f)
    cfg = {
        'reports': {'outputs': outputs or ['csv'], 'title': 'Test', 'top_n': 0},
        'paths':   {'templates_dir': None, 'cache_dir': cache,
                    'work_dir': str(tmp_path)},
        'profiles': {'active': {'security_fixes': 100}},
    }
    return cache, outdir, cfg


# ── _fmt_date ─────────────────────────────────────────────────────────────────
def test_fmt_date_unix_timestamp():
    result = _fmt_date(1700000000)
    assert '-' in result and ':' in result


def test_fmt_date_zero():
    # 0 is falsy in Python; _fmt_date guards with `if not ts: return ''`
    assert _fmt_date(0) == ''

def test_fmt_date_valid_unix():
    result = _fmt_date(1700000000)
    assert '-' in result and ':' in result  # YYYY-MM-DD HH:MM


def test_fmt_date_none():
    assert _fmt_date(None) == ''


def test_fmt_date_empty_string():
    assert _fmt_date('') == ''


def test_fmt_date_iso_string_fallback():
    """Non-integer ISO-like strings fall back to truncation."""
    result = _fmt_date('2024-05-01T12:34:56')
    assert result.startswith('2024-05-01T')


# ── _commit_rows ──────────────────────────────────────────────────────────────
def test_commit_rows_basic():
    rows = _commit_rows([_commit('abc', score=80, rank=1)])
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == 1        # rank
    assert 'abc' in row[1]   # sha (truncated to 12)
    assert row[12] == 80      # score (raw, now at index 12 after cherry_pickable)


def test_commit_rows_include_reason():
    c = _commit('xyz')
    c['_filter_reason'] = 'path_blacklist'
    rows = _commit_rows([c], include_reason=True)
    assert rows[0][-1] == 'path_blacklist'


def test_commit_rows_empty():
    assert _commit_rows([]) == []


def test_commit_rows_size_indicators():
    """Pick Priority, Score, Complexity, Cherry-Pickable + size columns are populated."""
    c = _commit('abc', score=80, rank=1)
    c['score_norm'] = 64
    c['scoring'] = {'profiles': {'security_fixes': 80}}
    c['stats'] = {'files_changed': 4, 'insertions': 30,
                  'deletions': 12, 'lines_changed': 42, 'hunks': 7}
    c['backport_complexity'] = 55
    c['pick_priority'] = 88
    rows = _commit_rows([c])
    row = rows[0]
    assert row[5] == 88          # pick_priority
    assert row[6] == 64          # score_norm (Score)
    assert row[7] == 55          # backport_complexity (Complexity)
    assert row[8] == ''           # cherry_pickable (empty string when not set)
    assert row[9] == 'security_fixes'        # profiles
    assert row[10] == 'security_fixes:80'     # profile_scores
    assert row[11] == 'config_map:CONFIG_USB'  # product_evidence
    assert row[12] == 80          # score (raw, hidden)
    assert row[13] == 4           # files_changed (hidden)
    assert row[14] == 42          # lines_changed (hidden)
    assert row[15] == 7           # hunks (hidden)


def test_commit_rows_size_indicators_default_zero_without_stats():
    rows = _commit_rows([_commit('abc', score=10, rank=1)])
    row = rows[0]
    assert row[5] == 0   # pick_priority
    assert row[6] == 0   # score_norm
    assert row[7] == 0   # backport_complexity
    assert row[8] == ''  # cherry_pickable (empty string when not set)
    assert row[9] == 'security_fixes'  # profiles
    assert row[12] == 10  # score (raw, hidden)
    assert row[13] == 0  # files_changed (hidden)
    assert row[14] == 0  # lines_changed (hidden)
    assert row[15] == 0  # hunks (hidden)

# ── AI Analysis ───────────────────────────────────────────────────────────
def _product_map_for_test():
    """Create a minimal product_map for testing product_evidence computation."""
    return {
        'config_enabled_map': {
            'CONFIG_USB': ['drivers/usb/core/hub.c'],
        },
        'config_enabled_dirs': ['drivers/usb/core'],
        'built_artifacts_from_dir': ['drivers/usb/core/hub.o'],
        'built_objects_from_log': ['hub.o'],
    }


def test_ai_analysis_input_written(tmp_path):
    """AI analysis input JSON is written when prefilter_kept commits exist."""
    cache, outdir, cfg = _setup(tmp_path, outputs=['csv'])
    # Write prefilter_kept cache file (required for AI analysis)
    from lib.manifest import CACHE_FILES
    prefilter_kept = [
        {
            'commit': 'a' * 40,
            'subject': 'fix: security vulnerability',
            'author_name': 'Dev One',
            'author_email': 'dev@linux.org',
            'author_org': 'linux',
            'author_time': 1700000000,
            'body': 'Fixes CVE-2024-1234\n\nDetailed description',
            'files': ['drivers/usb/core/hub.c'],
            'stats': {'files_changed': 1, 'lines_changed': 10, 'hunks': 1},
            'meta': {'is_fix': True, 'has_cve': True, 'has_syzbot': False, 'has_stable_cc': True},
            'prefilter_debug': {'filter_enabled': True},
        }
    ]
    import json
    with open(os.path.join(cache, CACHE_FILES['prefilter_kept']), 'w') as f:
        json.dump(prefilter_kept, f)
    with open(os.path.join(cache, CACHE_FILES['product_map']), 'w') as f:
        json.dump(_product_map_for_test(), f)
    
    run(cfg, cache, outdir)
    
    # Check AI input file was written
    ai_input_path = os.path.join(outdir, 'ai_analysis_input.json')
    assert os.path.exists(ai_input_path)
    
    # Validate content
    with open(ai_input_path, 'r') as f:
        ai_data = json.load(f)
    
    assert ai_data['version'] == '1.0'
    assert ai_data['total_commits'] == 1
    assert 'commits' in ai_data
    assert len(ai_data['commits']) == 1
    
    commit = ai_data['commits'][0]
    assert commit['commit'] == 'a' * 40
    assert commit['subject'] == 'fix: security vulnerability'
    assert commit['author_name'] == 'Dev One'
    assert commit['author_email'] == 'dev@linux.org'
    assert commit['author_org'] == 'linux'
    assert commit['meta']['has_cve'] is True
    assert commit['meta']['is_fix'] is True
    # Verify product_evidence is computed
    assert len(commit['product_evidence']) > 0
    # Verify prefilter_debug is NOT included
    assert 'prefilter_debug' not in commit
    # Verify no scoring/backport fields
    assert 'score' not in commit
    assert 'score_norm' not in commit
    assert 'matched_profiles' not in commit
    assert 'backport_complexity' not in commit
    assert 'pick_priority' not in commit


def test_ai_analysis_prompt_written(tmp_path):
    """AI analysis prompt template is written."""
    cache, outdir, cfg = _setup(tmp_path, outputs=['csv'])
    # Write prefilter_kept cache file (required for AI analysis)
    from lib.manifest import CACHE_FILES
    import json
    with open(os.path.join(cache, CACHE_FILES['prefilter_kept']), 'w') as f:
        json.dump([{'commit': 'x' * 40, 'subject': 'test', 'files': []}], f)
    with open(os.path.join(cache, CACHE_FILES['product_map']), 'w') as f:
        json.dump({}, f)
    
    run(cfg, cache, outdir)
    
    # Check prompt file was written
    prompt_path = os.path.join(outdir, 'ai_analysis_prompt.md')
    assert os.path.exists(prompt_path)
    
    # Validate content
    with open(prompt_path, 'r') as f:
        content = f.read()
    
    assert '# AI Analysis Prompt' in content
    assert 'ai_is_security_fix' in content
    assert 'ai_risks_if_not_backported' in content
    assert 'ai_backport_recommendation' in content


def test_ai_analysis_input_empty_prefilter_kept(tmp_path):
    """No AI files written when prefilter_kept is empty."""
    cache, outdir, cfg = _setup(tmp_path, outputs=['csv'])
    # Write empty prefilter_kept
    from lib.manifest import CACHE_FILES
    import json
    with open(os.path.join(cache, CACHE_FILES['prefilter_kept']), 'w') as f:
        json.dump([], f)
    with open(os.path.join(cache, CACHE_FILES['product_map']), 'w') as f:
        json.dump({}, f)
    
    run(cfg, cache, outdir)
    
    # AI files should not be written for empty input
    ai_input_path = os.path.join(outdir, 'ai_analysis_input.json')
    prompt_path = os.path.join(outdir, 'ai_analysis_prompt.md')
    assert not os.path.exists(ai_input_path)
    assert not os.path.exists(prompt_path)


def test_ai_analysis_schema_in_prompt(tmp_path):
    """AI analysis schema is defined in the prompt file, not in the JSON output."""
    cache, outdir, cfg = _setup(tmp_path, outputs=['csv'])
    from lib.manifest import CACHE_FILES
    import json
    prefilter_kept = [{'commit': 'x' * 40, 'subject': 'test', 'files': []}]
    with open(os.path.join(cache, CACHE_FILES['prefilter_kept']), 'w') as f:
        json.dump(prefilter_kept, f)
    with open(os.path.join(cache, CACHE_FILES['product_map']), 'w') as f:
        json.dump({}, f)
    
    run(cfg, cache, outdir)
    
    # Verify schema is NOT in the JSON output (it's in the prompt file)
    with open(os.path.join(outdir, 'ai_analysis_input.json'), 'r') as f:
        ai_data = json.load(f)
    
    assert 'schema' not in ai_data, 'Schema should not be in JSON output (it is in the prompt file)'
    assert 'commits' in ai_data
    
    # Verify the prompt file exists and contains schema definition
    prompt_path = os.path.join(outdir, 'ai_analysis_prompt.md')
    assert os.path.exists(prompt_path)
    with open(prompt_path, 'r') as f:
        prompt_content = f.read()
    assert 'schema' in prompt_content.lower() or 'fields' in prompt_content.lower()


# ── XLSX output ───────────────────────────────────────────────────────────────
def test_xlsx_output_written(tmp_path):
    pytest.importorskip('openpyxl')
    cache, outdir, cfg = _setup(tmp_path, outputs=['xlsx'])
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'relevant_commits.xlsx'))


def test_xlsx_summary_written(tmp_path):
    pytest.importorskip('openpyxl')
    cache, outdir, cfg = _setup(tmp_path, outputs=['xlsx'])
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'summary.xlsx'))


def test_xlsx_filtered_written(tmp_path):
    pytest.importorskip('openpyxl')
    flt = [_commit('d')]
    flt[0]['_filter_reason'] = 'path_blacklist'
    cache, outdir, cfg = _setup(tmp_path, filtered=flt, outputs=['xlsx'])
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'filtered_commits.xlsx'))


# ── ODS output ────────────────────────────────────────────────────────────────
def test_ods_output_written(tmp_path):
    cache, outdir, cfg = _setup(tmp_path, outputs=['ods'])
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'relevant_commits.ods'))


def test_ods_summary_written(tmp_path):
    cache, outdir, cfg = _setup(tmp_path, outputs=['ods'])
    run(cfg, cache, outdir)
    assert os.path.exists(os.path.join(outdir, 'summary.ods'))


def test_stage7_writes_metadata_sidecar(tmp_path):
    import json
    from lib.stages import st07_report
    cache = tmp_path / 'cache'; out = tmp_path / 'out'; cache.mkdir(); out.mkdir()
    from lib.manifest import CACHE_FILES
    commit = {'commit': 'b'*40, 'subject': 'fix', 'author_name': 'dev', 'author_time': 1, 'score': 10, 'matched_profiles': ['p1'], 'product_evidence': ['pe']}
    (cache / CACHE_FILES['relevant']).write_text(json.dumps([commit]))
    (cache / CACHE_FILES['filtered']).write_text('[]')
    (cache / CACHE_FILES['postfilter_dropped']).write_text('[]')
    (cache / CACHE_FILES['scored']).write_text(json.dumps([commit]))
    (cache / CACHE_FILES['commits']).write_text(json.dumps([commit]))
    (cache / CACHE_FILES['prefilter_kept']).write_text(json.dumps([commit]))
    cfg = {'paths': {'templates_dir': None}, 'git': {'repo_url': 'u', 'branch': 'main', 'base_rev': '111', 'head_rev': '222'}, 'reports': {'outputs': ['html'], 'top_n': 0, 'html_detail_mode': 'sidecar'}, 'profiles': {'active': {'p1': 100}}, '_meta': {'config_dir': str(tmp_path)}}
    st07_report.run(cfg, str(cache), str(out))
    meta = json.loads((out / 'report_metadata.json').read_text())
    assert meta['git']['branch'] == 'main'
    assert 'active_profiles' in meta['analysis']
    rows = json.loads((out / 'relevant_commits.table.json').read_text())
    assert 'product_evidence' not in rows[0]
