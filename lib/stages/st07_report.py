from lib.scoring import fmt_profiles, fmt_evidence, order_commit_details
"""Stage 07 logic: generate all output formats.

Changes:
  v12.0.0 (A.3) -- update_stage_progress() from lib.pipeline_runtime is
                  now called with the correct signature.
  v19.4.0       -- Two cherry-pick execution shell scripts are now generated
                  (lib/cherrypick_script_gen.py) when collect.cherry_pick_test
                  is enabled and kernel.rev_old is configured.
  v19.5.0       -- Cherry-pick generation changed to single script + JSON data
                  file design (cherry_pick.sh + cherry_pick_data.json).
                  Both files are written to output/ directory for easy export.
  v19.6.0       -- Merged config dump (pipeline_config.json) written to output/
                  as a manifest for reproducibility.
  v19.7.0       -- pipeline_config.json now preserves non-expanded variable
                  references (e.g., ${WORKSPACE}/work) for better reproducibility.
"""
import csv
import json
import logging
import os
import shutil
from lib.config import load_json, save_json
from lib.html_report import generate_html_report
from lib.manifest import CACHE_FILES
from lib.run_stats import build_run_stats


# Column definitions imported from manifest (single source of truth)
from lib.manifest import COMMIT_COLS as _MC, COMMIT_COLS_FILTERED as _MCF
# Use lowercase keys for CSV row construction; headers come from manifest
_COMMIT_KEYS          = ["rank", "sha", "subject", "author_org", "date",
                         "score", "profiles"]
_COMMIT_KEYS_FILTERED = _COMMIT_KEYS + ["filter_reason"]

# Total number of progress milestones emitted by run().
# Used both in _update_stage7_progress() and in the final finish call.
_STAGE7_MILESTONES = 8

# v18.2.0: Module-level progress hooks so tests can monkeypatch them.
try:
    from lib.pipeline_runtime import update_stage_progress as _rt_progress_f
    from lib.pipeline_runtime import finish_progress_line  as _rt_finish_line_f
except Exception:
    _rt_progress_f    = None
    _rt_finish_line_f = None


def _fmt_date(ts):
    """Format a Unix timestamp or ISO string as YYYY-MM-DD HH:MM."""
    if not ts:
        return ''
    try:
        import datetime
        return datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return str(ts)[:16]


def _commit_rows(commits, include_reason=False):
    """Build list-of-lists rows for CSV / XLSX / ODS output."""
    rows = []
    for c in commits:
        sc       = (c.get('scoring') or {})
        profiles = (sc.get('profiles') or {})
        prof_scores = '; '.join(
            '%s:%g' % (p, profiles.get(p, 0))
            for p in sorted(profiles)
        )
        stats = c.get('stats') or {}
        cp_val = c.get('cherry_pickable')
        if cp_val is True:
            cherry_pick_str = 'Yes'
        elif cp_val is False:
            cherry_pick_str = 'No'
        else:
            cherry_pick_str = ''
        row = [
            c.get('_rank', ''),
            (c.get('commit') or '')[:12],
            c.get('subject', ''),
            c.get('author_org', ''),
            _fmt_date(c.get('author_time', '')),
            c.get('pick_priority', 0) or 0,
            c.get('score_norm', 0) or 0,
            c.get('backport_complexity', 0) or 0,
            cherry_pick_str,
            fmt_profiles(c),
            prof_scores,
            fmt_evidence(c),
            c.get('score', 0) or 0,
            stats.get('files_changed', 0) or 0,
            stats.get('lines_changed', 0) or 0,
            stats.get('hunks', 0) or 0,
        ]
        if include_reason:
            row.append(c.get('_filter_reason', ''))
        rows.append(row)
    return rows


def _trace_summary(commit):
    trace = (((commit or {}).get('scoring') or {}).get('trace') or {}).get('profiles') or {}
    parts = []
    for pname in sorted(trace):
        pdata = trace.get(pname) or {}
        rules = pdata.get('rules') or {}
        matched = sum(1 for rv in rules.values() if (rv or {}).get('matched'))
        parts.append('%s:%s/%s=%s' % (pname, matched, len(rules), pdata.get('final_score', 0)))
    return '; '.join(parts)


TRACE_COLS = ['sha', 'profile', 'rule', 'matched_level', 'rule_score', 'profile_score', 'pattern_type', 'pattern', 'matched_value']

def _trace_rows(scored):
    header = TRACE_COLS
    rows = []
    for c in scored or []:
        sha = (c.get('commit') or '')[:12]
        trace = (((c.get('scoring') or {}).get('trace') or {}).get('profiles') or {})
        for pname in sorted(trace):
            pdata = trace.get(pname) or {}
            pscore = pdata.get('final_score', 0)
            rules = pdata.get('rules') or {}
            if not rules:
                rows.append([sha, pname, '', '', 0, pscore, '', '', ''])
                continue
            for rname in sorted(rules):
                rdata = rules.get(rname) or {}
                matches = rdata.get('matches') or {}
                emitted = False
                for kind in ['keywords_whitelist', 'path_whitelist', 'commit_whitelist']:
                    for m in (matches.get(kind) or []):
                        rows.append([sha, pname, rname, rdata.get('matched_level', ''), rdata.get('score', 0), pscore, kind, m.get('pattern', ''), m.get('value', '')])
                        emitted = True
                if not emitted:
                    rows.append([sha, pname, rname, rdata.get('matched_level', ''), rdata.get('score', 0), pscore, '', '', ''])
    return header, rows


def _canonical_commit(commit):
    return order_commit_details(commit)


def _write_commit_details(root, commits):
    """Write commit detail JSON files into bucket layout."""
    if not commits:
        return 0
    os.makedirs(root, exist_ok=True)
    buckets = {}
    seen = set()
    for c in commits:
        full = c.get('commit') or ''
        if not full or full in seen or len(full) < 3:
            continue
        seen.add(full)
        bdir  = os.path.join(root, full[0])
        bfile = os.path.join(bdir, full[1:3] + '.json')
        if bfile not in buckets:
            buckets[bfile] = (bdir, {})
        buckets[bfile][1][full] = _canonical_commit(c)
    written = 0
    seen_dirs = set()
    for bfile, (bdir, data) in buckets.items():
        if bdir not in seen_dirs:
            os.makedirs(bdir, exist_ok=True)
            seen_dirs.add(bdir)
        _save_ordered_json(bfile, data)
        written += len(data)
    return written


def _write_table_json(path, commits, include_reason=False):
    rows = []
    for c in commits:
        stats = c.get('stats') or {}
        cp_val = c.get('cherry_pickable')
        row = {
            'commit': c.get('commit', ''),
            'subject': c.get('subject', ''),
            'author_name': c.get('author_name', ''),
            'author_email': c.get('author_email', ''),
            'author_org': c.get('author_org', ''),
            'author_time': c.get('author_time', ''),
            'score': c.get('score', 0) or 0,
            'score_norm': c.get('score_norm', 0) or 0,
            'files_changed': stats.get('files_changed', 0) or 0,
            'lines_changed': stats.get('lines_changed', 0) or 0,
            'hunks': stats.get('hunks', 0) or 0,
            'backport_complexity': c.get('backport_complexity', 0) or 0,
            'pick_priority': c.get('pick_priority', 0) or 0,
            'cherry_pickable': cp_val,
            'matched_profiles': list(c.get('matched_profiles') or []),
        }
        if include_reason and c.get('_filter_reason', ''):
            row['_filter_reason'] = c.get('_filter_reason', '')
        rows.append(order_commit_details(row))
    _save_compact_json(path, rows)


def _profile_summary(scored, profile_rules):
    """Per-profile commit count, total score, and average score."""
    summary = {}
    for pname in (profile_rules or {}):
        matched = [c for c in scored if pname in (c.get('matched_profiles') or [])]
        scores  = [c.get('score', 0) or 0 for c in matched]
        summary[pname] = {
            'description':  (profile_rules.get(pname) or {}).get('description', ''),
            'commit_count': len(matched),
            'total_score':  sum(scores),
            'avg_score':    round(sum(scores) / len(scores), 1) if scores else 0,
        }
    return summary


def _profile_matrix(scored):
    """Returns header list + list-of-rows for profile matrix CSV."""
    profiles = sorted({p for c in scored for p in (c.get('matched_profiles') or [])})
    header   = ['rank', 'sha12', 'score', 'subject'] + profiles
    rows     = []
    for c in scored:
        sc = (c.get('scoring') or {})
        ps = (sc.get('profiles') or {})
        row = [
            c.get('_rank', ''),
            (c.get('commit') or '')[:12],
            c.get('score', 0) or 0,
            c.get('subject', ''),
        ] + [ps.get(p, 0) for p in profiles]
        rows.append(row)
    return header, rows


def _coverage_metrics(scored):
    """Return diagnostic coverage counters included in report_stats.json."""
    return {
        'commits_matched_zero_profiles':
            sum(1 for c in scored if not (c.get('matched_profiles') or [])),
        'commits_with_product_evidence':
            sum(1 for c in scored if c.get('product_evidence')),
    }


def _build_evaluation_block(cfg, outputs, html_detail_mode, top_n, threshold):
    """A.4 / D.14: Build the evaluation metadata block for report_stats."""
    git       = cfg.get('git', {}) or {}
    reports   = cfg.get('reports', {}) or {}
    active    = sorted((cfg.get('profiles', {}) or {}).get('active', {}).keys())

    repo_url  = git.get('repo_url') or git.get('remote_url') or ''
    branch    = git.get('branch') or ''
    base_rev  = git.get('base_rev') or ''
    head_rev  = git.get('head_rev') or ''
    git_range = f'{base_rev}..{head_rev}' if base_rev and head_rev else ''

    return {
        'git_source':       f'{repo_url} ({branch})' if repo_url and branch else repo_url or branch or None,
        'git_baseline':     base_rev or None,
        'git_range':        git_range or None,
        'kernel_revision':  git.get('kernel_version') or git.get('kernel_revision') or None,
        'profiles':         ', '.join(active) if active else None,
        'top_n':            str(top_n) if top_n else 'unlimited',
        'min_score':        str(threshold) if threshold else None,
        'html_detail_mode': html_detail_mode,
        'outputs':          ', '.join(sorted(outputs)),
    }


def _save_ordered_json(path, data):
    """Write data as indented JSON (indent=2).  Used for shard detail files."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        f.write('\n')


def _save_compact_json(path, data):
    """G.1: Write data as compact JSON (no indentation, minimal separators)."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, default=str, separators=(',', ':'))
        f.write('\n')


def _resolve_outputs(cfg):
    """Return the set of output format names to produce."""
    reports   = cfg.get('reports', {}) or {}
    outputs_l = reports.get('outputs')

    if outputs_l is not None:
        return {str(o).lower() for o in (outputs_l or [])}

    return {'csv', 'html'}


def _top_n(cfg):
    """Return the top-N limit, or None when top_n is 0 (meaning no limit)."""
    reports = cfg.get('reports', {}) or {}
    val = reports.get('top_n')
    if val is None:
        return 5000
    n = int(val)
    return None if n == 0 else n


def _report_title(cfg):
    tmpl = cfg.get('reports', {}) or {}
    return tmpl.get('title', 'kcommit Analysis Report')


def _load_profile_rules_safe(cfg, cache):
    """Load profile rules, falling back to compiled_rules.json in cache."""
    from lib.profile_rules import load_profile_rules
    try:
        return load_profile_rules(cfg)
    except Exception as exc:
        cr_path = os.path.join(cache, CACHE_FILES.get('compiled_rules', 'compiled_rules.json'))
        if not os.path.exists(cr_path):
            logging.warning('load_profile_rules failed and no compiled_rules.json: %s', exc)
            return {}
        logging.debug('load_profile_rules failed (%s); inflating from %s', exc, cr_path)
        try:
            raw = load_json(cr_path, default={}) or {}
            rules_body   = raw.get('rules', {}) or {}
            profiles_raw = raw.get('profiles', {}) or {}
            inflated = {}
            for pname, pmeta in profiles_raw.items():
                rule_weights = (pmeta.get('rules') or {})
                rules_inflated = {}
                for rname, rmeta in rule_weights.items():
                    body = dict(rules_body.get(rname) or {})
                    body['weight'] = (rmeta or {}).get('weight', 0)
                    rules_inflated[rname] = body
                inflated[pname] = {
                    'merged': pmeta.get('merged') or {},
                    'rules':  rules_inflated,
                }
            return inflated
        except Exception as exc2:
            logging.warning('compiled_rules.json inflation failed: %s', exc2)
            return {}


def _build_ai_analysis_schema():
    """Return the schema description for AI analysis input."""
    return {
        'version': '1.0',
        'description': 'Schema for commits passed to AI for backport triage analysis',
        'fields': {
            'commit': {'type': 'string', 'description': 'Full SHA-1 hash of the commit'},
            'subject': {'type': 'string', 'description': 'Commit subject line (title)'},
            'author_name': {'type': 'string', 'description': 'Name of the commit author'},
            'author_email': {'type': 'string', 'description': 'Email address of the commit author'},
            'author_org': {'type': 'string', 'description': 'Organization extracted from the email domain'},
            'author_time': {'type': 'integer', 'description': 'Unix timestamp of the commit date'},
            'body': {'type': 'string', 'description': 'Full commit message body (excluding subject)'},
            'files': {'type': 'array', 'description': 'List of file paths modified by this commit', 'items': {'type': 'string'}},
            'stats': {'type': 'object', 'description': 'Commit size indicators'},
            'meta': {'type': 'object', 'description': 'Linux kernel commit annotation flags'},
            'product_evidence': {'type': 'array', 'description': 'List of product relevance evidence tags'},
        },
    }


def _build_ai_analysis_input(cfg, prefilter_kept_commits, product_map):
    """Build the AI analysis input JSON structure."""
    from lib.manifest import VERSION
    from lib.scoring import _collect_product_evidence
    import datetime
    
    commits_for_ai = []
    for c in prefilter_kept_commits:
        evidence = _collect_product_evidence(c, product_map) if product_map else []
        commit_data = {
            'commit': c.get('commit', ''),
            'subject': c.get('subject', ''),
            'author_name': c.get('author_name', ''),
            'author_email': c.get('author_email', ''),
            'author_org': c.get('author_org', ''),
            'author_time': c.get('author_time', 0),
            'body': c.get('body', ''),
            'files': list(c.get('files') or []),
            'stats': c.get('stats') or {},
            'meta': c.get('meta') or {},
            'product_evidence': evidence,
        }
        commits_for_ai.append(commit_data)
    
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
    except AttributeError:
        now = datetime.datetime.utcnow()
    return {
        'version': '1.0',
        'pipeline_version': VERSION,
        'purpose': 'Input for AI analysis to triage commits for backporting',
        'generated_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'total_commits': len(commits_for_ai),
        'schema': _build_ai_analysis_schema(),
        'commits': commits_for_ai,
    }


def _get_ai_analysis_prompt(cfg):
    """Load AI analysis prompt from config file."""
    ai_cfg = cfg.get('ai', {}) or {}
    prompt_path = ai_cfg.get('prompt_path')
    
    if not prompt_path:
        prompt_path = os.path.join(cfg['paths'].get('configdir', 'configs'), 'ai', 'ai_analysis_prompt.md')
    
    if not os.path.exists(prompt_path):
        logging.warning('AI analysis prompt not found at %s, using empty prompt', prompt_path)
        return ''
    
    with open(prompt_path, 'r', encoding='utf-8') as f:
        return f.read()


def _write_ai_analysis_files(cfg, cache, outdir):
    """Write AI analysis input JSON and prompt template files."""
    written = []
    
    prefilter_kept = load_json(
        os.path.join(cache, CACHE_FILES['prefilter_kept']), default=[]
    ) or []
    
    product_map = load_json(
        os.path.join(cache, CACHE_FILES['product_map']), default={}
    ) or {}
    
    if not prefilter_kept:
        return written
    
    ai_cfg = cfg.get('ai', {}) or {}
    chunk_size = int(ai_cfg.get('chunk_size', 0) or 0)
    
    ai_input = _build_ai_analysis_input(cfg, prefilter_kept, product_map)
    
    if chunk_size > 0:
        import math
        total_commits = len(ai_input['commits'])
        num_chunks = math.ceil(total_commits / chunk_size)
        
        chunk_dir = os.path.join(outdir, 'ai_analysis_input')
        os.makedirs(chunk_dir, exist_ok=True)
        
        for i in range(num_chunks):
            start_idx = i * chunk_size
            end_idx = min(start_idx + chunk_size, total_commits)
            
            chunk_input = {
                'version': ai_input['version'],
                'pipeline_version': ai_input['pipeline_version'],
                'purpose': ai_input['purpose'],
                'generated_at': ai_input['generated_at'],
                'total_commits': end_idx - start_idx,
                'chunk_info': {
                    'chunk_number': i + 1,
                    'total_chunks': num_chunks,
                    'start_index': start_idx,
                    'end_index': end_idx - 1,
                },
                'commits': ai_input['commits'][start_idx:end_idx],
            }
            
            chunk_filename = str(i + 1).zfill(len(str(num_chunks))) + '.json'
            chunk_path = os.path.join(chunk_dir, chunk_filename)
            _save_ordered_json(chunk_path, chunk_input)
            written.append(chunk_path)
        
        logging.info('AI analysis input split into %d chunks (%d commits/chunk)', num_chunks, chunk_size)
    else:
        ai_input_out = {k: v for k, v in ai_input.items() if k != 'schema'}
        ai_input_path = os.path.join(outdir, 'ai_analysis_input.json')
        _save_ordered_json(ai_input_path, ai_input_out)
        written.append(ai_input_path)
    
    prompt_path = os.path.join(outdir, 'ai_analysis_prompt.md')
    prompt_content = _get_ai_analysis_prompt(cfg)
    if prompt_content:
        with open(prompt_path, 'w', encoding='utf-8') as f:
            f.write(prompt_content)
        written.append(prompt_path)
    
    return written


def _write_cherry_pick_scripts(cfg, cache, outdir):
    """Write cherry_pick.sh and cherry_pick_data.json to output directory.

    v19.5.0: Single script + JSON data file design.
    Only runs when collect.cherry_pick_test is enabled and kernel.rev_old is
    configured.

    The script loads cherry_pick_data.json from the same directory, so both
    files are placed in outdir (not cache/). This allows the output/ folder
    to be exported/archived independently.

    Generation is best-effort: any failure is logged as a warning and does
    not abort the report stage (mirrors serve_report.pyz's error handling).

    Returns list of paths written (empty list when the feature is disabled
    or nothing was cherry-pickable).
    """
    written = []
    collect = cfg.get('collect', {}) or {}
    kernel  = cfg.get('kernel', {}) or {}

    if not collect.get('cherry_pick_test') or not kernel.get('rev_old'):
        return written

    try:
        from lib.cherrypick_script_gen import write_cherry_pick_files
    except Exception as exc:
        logging.warning('cherry-pick script generation unavailable: %s', exc)
        return written

    try:
        script_path, data_path, stats = write_cherry_pick_files(cfg, cache, outdir)
        if script_path and data_path:
            written.append(script_path)
            written.append(data_path)
            logging.info(
                'cherry_pick.sh + cherry_pick_data.json: %d cherry-pickable '
                '(relevant: %d, prefiltered-only: %d) / %d tested / %d total',
                stats['cherry_pickable'], stats['relevant_count'], 
                stats['prefiltered_count'], stats['tested'], stats['total_in_set'],
            )
        else:
            logging.info(
                'cherry_pick files not written: no cherry-pickable commits found '
                '(total_in_set=%d, tested=%d)',
                stats['total_in_set'], stats['tested'],
            )
    except Exception as exc:
        logging.warning('cherry_pick_generation failed: %s', exc)

    return written


def _dump_merged_config(cfg, raw_cfg, outdir):
    """Dump the merged config to output/ as a manifest for reproducibility.
    
    This uses the raw (non-expanded) config to preserve variable references
    like ${WORKSPACE}/work in the manifest, making it more portable and
    reproducible across different environments.
    
    Internal metadata (_meta, standalone config_dir) are filtered out to keep the
    manifest clean and focused on user-facing configuration.
    
    Returns the path written, or None on error.
    """
    try:
        # Use raw_cfg (non-expanded) to preserve variable references
        dump_cfg = {k: v for k, v in raw_cfg.items() if k not in ('_meta', 'config_dir')}
        config_path = os.path.join(outdir, 'pipeline_config.json')
        _save_ordered_json(config_path, dump_cfg)
        return config_path
    except Exception as exc:
        logging.warning('pipeline_config.json write failed: %s', exc)
        return None


def run(cfg, cache, outdir):
    """Stage 07 entry point: generate all output formats."""
    try:
        from lib.spreadsheet import (
            write_xlsx, write_ods,
            write_profile_summary_xlsx, write_profile_matrix_xlsx,
            write_profile_summary_ods,  write_profile_matrix_ods,
            write_summary_xlsx, write_summary_ods,
        )
    except ImportError:
        write_xlsx = write_ods = None

    outputs  = _resolve_outputs(cfg)
    top_n    = _top_n(cfg)
    title    = _report_title(cfg)
    reports_cfg = cfg.get('reports', {}) or {}
    html_detail_mode = reports_cfg.get('html_detail_mode', 'sidecar')
    html_embed_compression = reports_cfg.get('html_embed_compression', 'none')
    stage_state_path = os.path.join(outdir, 'runtime_status.json')
    os.makedirs(outdir, exist_ok=True)
    
    # Build raw (non-expanded) config for manifest
    config_path = cfg.get('_meta', {}).get('config_path')
    if config_path:
        from lib.config import load_config_with_raw
        try:
            _, raw_cfg = load_config_with_raw(config_path)
        except Exception as exc:
            logging.warning('load_config_with_raw failed, using expanded cfg for manifest: %s', exc)
            raw_cfg = cfg
    else:
        raw_cfg = cfg
    
    # Dump merged config as manifest for reproducibility (using raw config)
    config_dump_path = _dump_merged_config(cfg, raw_cfg, outdir)
    
    _written = []
    if config_dump_path:
        _written.append(os.path.relpath(config_dump_path, outdir))

    def _emit(path):
        try:
            _written.append(os.path.relpath(path, outdir))
        except ValueError:
            _written.append(path)

    def _update_stage7_progress(current, total, message):
        payload = {
            'current': int(current),
            'total': max(1, int(total)),
            'message': message,
        }
        save_json(stage_state_path, {
            'stage': 'report_commits',
            'stage_number': 7,
            'stage_total': 7,
            'progress': payload,
        })
        if _rt_progress_f is not None:
            try:
                frac = float(current) / max(1, float(total))
                _rt_progress_f(
                    7, 7, frac, message,
                    n_done=int(current), n_total=int(total),
                )
            except Exception as _e:
                logging.debug('update_stage_progress (st07) failed: %s', _e)

    scored        = (load_json(os.path.join(cache, CACHE_FILES['relevant']), default=[]) or [])
    if top_n is not None:
        scored = scored[:top_n]
    prefiltered   = load_json(os.path.join(cache, CACHE_FILES['filtered']), default=[]) or []
    postfiltered  = load_json(os.path.join(cache, CACHE_FILES['postfilter_dropped']), default=[]) or []
    filtered      = list(prefiltered) + list(postfiltered)
    profile_rules = _load_profile_rules_safe(cfg, cache)

    _all_scored  = load_json(os.path.join(cache, CACHE_FILES['scored']), default=[]) or []
    _collected   = load_json(os.path.join(cache, CACHE_FILES['commits']), default=[]) or []
    _pf_kept     = load_json(os.path.join(cache, CACHE_FILES['prefilter_kept']), default=[]) or []
    _threshold   = (lambda filt: float(filt.get('min_score', 0) or 0))(cfg.get('filter', {}) or {})
    _scores_all  = [float(c.get('score', 0) or 0) for c in scored]

    report_stats = {
        'st01_collected':           len(_collected),
        'st04_prefilter_kept':      len(_pf_kept),
        'st04_prefilter_dropped':   len(_collected) - len(_pf_kept),
        'st05_total_scored':        len(_all_scored),
        'st06_threshold':           _threshold,
        'st06_postfilter_dropped':  len(postfiltered),
        'total_scored_commits':     len(scored),
        'top_n':                    top_n,
        'score_highest':            max(_scores_all) if _scores_all else 0,
        'score_lowest':             min(_scores_all) if _scores_all else 0,
        'score_avg':                round(sum(_scores_all) / len(_scores_all), 1) if _scores_all else 0,
        **_coverage_metrics(scored),
        'evaluation': _build_evaluation_block(
            cfg, outputs, html_detail_mode, top_n, _threshold),
    }
    prof_summary      = _profile_summary(scored, profile_rules)
    mat_hdr, mat_rows = _profile_matrix(scored)
    details_root = os.path.join(outdir, 'commits')
    _write_commit_details(details_root, list(scored) + list(filtered))

    _update_stage7_progress(1, _STAGE7_MILESTONES, 'Writing relevant_commits.json')
    _p = os.path.join(outdir, 'relevant_commits.json')
    _save_compact_json(_p, [_canonical_commit(c) for c in scored]);  _emit(_p)
    _p = os.path.join(outdir, 'profile_summary.json')
    _save_compact_json(_p, prof_summary);  _emit(_p)
    _p = os.path.join(outdir, 'profile_matrix.json')
    _save_compact_json(_p, {'header': mat_hdr, 'rows': mat_rows});  _emit(_p)
    trace_hdr, trace_rows = _trace_rows(scored)
    _p = os.path.join(outdir, 'rule_trace.json')
    _save_compact_json(_p, {'header': trace_hdr, 'rows': trace_rows});  _emit(_p)
    if filtered:
        _p = os.path.join(outdir, 'filtered_commits.json')
        _save_compact_json(_p, [_canonical_commit(c) for c in filtered]);  _emit(_p)

    _pf_debug_src = os.path.join(cache, CACHE_FILES.get('prefilter_debug', 'prefilter_debug.json'))
    if os.path.exists(_pf_debug_src):
        _pf_debug_dst = os.path.join(outdir, 'prefilter_debug.json')
        shutil.copy2(_pf_debug_src, _pf_debug_dst)
        _emit(_pf_debug_dst)

    _update_stage7_progress(2, _STAGE7_MILESTONES, 'Writing rule_trace.csv')
    if 'csv' in outputs:
        _rtcsv = os.path.join(outdir, 'rule_trace.csv')
        try:
            with open(_rtcsv, 'w', newline='', encoding='utf-8') as _fh:
                _w = csv.writer(_fh)
                _w.writerow(trace_hdr)
                _w.writerows(trace_rows)
            _emit(_rtcsv)
        except Exception as _e:
            logging.warning('rule_trace.csv write failed: %s', _e)

    _update_stage7_progress(3, _STAGE7_MILESTONES, 'Writing CSV outputs')
    if 'csv' in outputs:
        csv_path = os.path.join(outdir, 'relevant_commits.csv')
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(_MC)
            w.writerows(_commit_rows(scored))
        _emit(csv_path)
        mat_path = os.path.join(outdir, 'profile_matrix.csv')
        with open(mat_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(mat_hdr)
            w.writerows(mat_rows)
        _emit(mat_path)
        ps_path = os.path.join(outdir, 'profile_summary.csv')
        with open(ps_path, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(['profile', 'count', 'total_score', 'avg_score'])
            for pname, pd in sorted(prof_summary.items(),
                                    key=lambda kv: kv[1].get('commit_count', 0),
                                    reverse=True):
                w.writerow([pname, pd.get('commit_count', 0),
                             pd.get('total_score', 0), pd.get('avg_score', 0)])
        _emit(ps_path)
        if filtered:
            flt_path = os.path.join(outdir, 'filtered_commits.csv')
            with open(flt_path, 'w', newline='', encoding='utf-8') as fh:
                w = csv.writer(fh)
                w.writerow(_MCF)
                w.writerows(_commit_rows(filtered, include_reason=True))
            _emit(flt_path)

    metadata = {
        'report_title': title,
        'git': cfg.get('git', {}) or {},
        'analysis': {
            'top_n': top_n,
            'outputs': sorted(outputs),
            'html_detail_mode': html_detail_mode,
            'html_embed_compression': html_embed_compression,
            'filter': cfg.get('filter', {}) or {},
            'reports': reports_cfg,
            'active_profiles': sorted((cfg.get('profiles', {}) or {}).get('active', {}).keys()),
        },
        'report_stats': report_stats,
        'profile_summary': prof_summary,
    }

    _update_stage7_progress(4, _STAGE7_MILESTONES, 'Writing XLSX / ODS outputs')
    if 'xlsx' in outputs:
        if write_xlsx:
            try:
                write_xlsx(os.path.join(outdir, 'relevant_commits.xlsx'),
                           scored, prof_summary,
                           sheet_name='Relevant Commits')
                _emit(os.path.join(outdir, 'relevant_commits.xlsx'))
            except Exception as e:
                logging.warning('XLSX failed: %s', e)
            if filtered:
                try:
                    write_xlsx(os.path.join(outdir, 'filtered_commits.xlsx'),
                               filtered, {},
                               sheet_name='Filtered Commits',
                               include_reason=True)
                    _emit(os.path.join(outdir, 'filtered_commits.xlsx'))
                except Exception as e:
                    logging.warning('XLSX filtered failed: %s', e)
            try:
                write_profile_summary_xlsx(
                    os.path.join(outdir, 'profile_summary.xlsx'), prof_summary)
            except Exception as e:
                logging.warning('XLSX profile_summary failed: %s', e)
            try:
                write_profile_matrix_xlsx(
                    os.path.join(outdir, 'profile_matrix.xlsx'), scored)
            except Exception as e:
                logging.warning('XLSX profile_matrix failed: %s', e)
            try:
                write_summary_xlsx(os.path.join(outdir, 'summary.xlsx'),
                                   scored, filtered, prof_summary,
                                   report_stats=report_stats,
                                   report_title=title)
                _emit(os.path.join(outdir, 'summary.xlsx'))
            except Exception as e:
                logging.warning('XLSX summary failed: %s', e)
        else:
            logging.warning("'xlsx' output requested but lib.spreadsheet not available")

    if 'ods' in outputs:
        if write_ods:
            try:
                write_ods(os.path.join(outdir, 'relevant_commits.ods'),
                          scored, prof_summary,
                          sheet_name='Relevant Commits')
            except Exception as e:
                logging.warning('ODS failed: %s', e)
            if filtered:
                try:
                    write_ods(os.path.join(outdir, 'filtered_commits.ods'),
                              filtered, {},
                              sheet_name='Filtered Commits',
                              include_reason=True)
                    _emit(os.path.join(outdir, 'filtered_commits.ods'))
                except Exception as e:
                    logging.warning('ODS filtered failed: %s', e)
            try:
                write_profile_summary_ods(
                    os.path.join(outdir, 'profile_summary.ods'), prof_summary)
            except Exception as e:
                logging.warning('ODS profile_summary failed: %s', e)
            try:
                write_profile_matrix_ods(
                    os.path.join(outdir, 'profile_matrix.ods'), scored)
            except Exception as e:
                logging.warning('ODS profile_matrix failed: %s', e)
            try:
                write_summary_ods(os.path.join(outdir, 'summary.ods'),
                                  scored, filtered, prof_summary,
                                  report_stats=report_stats,
                                  report_title=title)
                _emit(os.path.join(outdir, 'summary.ods'))
            except Exception as e:
                logging.warning('ODS summary failed: %s', e)
        else:
            logging.warning("'ods' output requested but lib.spreadsheet not available")

    _update_stage7_progress(5, _STAGE7_MILESTONES, 'Building run statistics')
    run_stats_data = None
    try:
        _prs_path = os.path.join(outdir, CACHE_FILES['run_stats'])
        run_stats_data = build_run_stats(cfg, cache, outdir)
        _emit(_prs_path)
    except Exception as _e:
        logging.warning('pipeline_run_stats.json write failed: %s', _e)

    _update_stage7_progress(6, _STAGE7_MILESTONES, 'Writing report metadata sidecar')
    _hp = None
    if 'html' in outputs:
        try:
            _save_ordered_json(os.path.join(outdir, 'report_metadata.json'), metadata)
            _emit(os.path.join(outdir, 'report_metadata.json'))
            _update_stage7_progress(7, _STAGE7_MILESTONES, 'Generating HTML report')
            _hp = os.path.join(outdir, 'summary.html')
            _tp = os.path.join(outdir, 'relevant_commits.table.json')
            _write_table_json(_tp, scored, include_reason=False)
            _emit(_tp)
            if filtered:
                _ftp = os.path.join(outdir, 'filtered_commits.table.json')
                _write_table_json(_ftp, filtered, include_reason=True)
                _emit(_ftp)
            generate_html_report(
                scored, prof_summary, report_stats, _hp,
                title=title,
                templates_dir=cfg['paths'].get('templates_dir'),
                detail_mode=html_detail_mode,
                commit_index_path='./relevant_commits.table.json' if html_detail_mode == 'sidecar' else None,
                commit_detail_root='./commits',
                embed_compression=html_embed_compression,
                metadata_path='./report_metadata.json' if html_detail_mode == 'sidecar' else None,
                cfg=cfg,
                run_stats_data=run_stats_data,
                filtered_commits=filtered if filtered else None,
            )
            _emit(_hp)
        except Exception as e:
            logging.warning('HTML report failed: %s', e)
            _hp = None

        _update_stage7_progress(8, _STAGE7_MILESTONES, 'Generating serve_report.pyz')
        if _hp and os.path.exists(_hp):
            try:
                from lib.serve_script_gen import generate_serve_script
                _srv_path = os.path.join(outdir, 'serve_report.pyz')
                _srv_stats = generate_serve_script(
                    html_path=_hp,
                    commits_root=details_root,
                    output_path=_srv_path,
                )
                _emit(_srv_path)
                logging.info(
                    'serve_report.pyz: %.1f KB raw -> %.1f KB compressed (%.0f%% reduction)',
                    _srv_stats['raw_kb'], _srv_stats['compressed_kb'], _srv_stats['ratio_pct'],
                )
            except Exception as _srv_e:
                logging.warning('serve_report.pyz generation failed: %s', _srv_e)

    _update_stage7_progress(_STAGE7_MILESTONES, _STAGE7_MILESTONES, 'Done')
    if _rt_finish_line_f is not None:
        try:
            _rt_finish_line_f()
        except Exception as _e:
            logging.debug('finish_progress_line (st07) failed: %s', _e)

    ai_written = _write_ai_analysis_files(cfg, cache, outdir)
    _written.extend(ai_written)

    cp_script_written = _write_cherry_pick_scripts(cfg, cache, outdir)
    _written.extend(cp_script_written)

    report_stats['generated_files'] = sorted(set(
        f for f in _written if f != 'report_stats.json'))
    save_json(os.path.join(outdir, 'report_stats.json'), report_stats)
    return report_stats
