from lib.scoring import fmt_profiles, fmt_evidence, order_commit_details
"""Stage 07 logic: generate all output formats.

Changes:
  v12.0.0 (A.3) — update_stage_progress() from lib.pipeline_runtime is
                  now called with the correct signature:
                    update_stage_progress(stage_index, stage_total,
                                          frac, label,
                                          n_done=current, n_total=total)
                  Previously the call passed `current` as `frac` and
                  `total` as `label`, which produced a TypeError on TTYs
                  and sent meaningless values to the progress bar.
  v12.0.0 (A.4) — report_stats['evaluation'] is now populated from cfg
                  before being passed to generate_html_report(), enabling
                  the Evaluation sidebar section in the HTML report.
  v12.0.0 (A.5) — _commit_rows() docstring clarified: the function still
                  appends a product_evidence cell for CSV/XLSX/ODS output
                  (COMMIT_COLS includes that column). Only the HTML table
                  hides the column (handled in html_report.py / A.1).
  v12.0.0 (A.3) — rule_trace.csv is now written alongside rule_trace.json
                  so human analysts can open it directly in a spreadsheet.
                  rule_trace.csv is only written when CSV output is enabled
                  (same guard as relevant_commits.csv).
                  _STAGE7_MILESTONES bumped from 6 to 7 to account for the
                  extra CSV milestone.
  v13.0.0       — prefilter_debug.json is copied from cache to outdir when
                  it exists, and listed in report_stats['generated_files'].
  v13.0.0       — load_profile_rules() failure (e.g. no active profiles) is
                  handled gracefully: when compiled_rules.json is already
                  present in cache the inflated in-memory form is derived
                  from it directly, so the stage does not abort.
  v14.1.0       — build_run_stats() from lib.run_stats is called at the end
                  of run(); it writes pipeline_run_stats.json in outdir.
                  This file contains exhaustive, pre-aggregated pipeline-run
                  statistics for the HTML report right-pane "Global Stats"
                  panel.  'pipeline_run_stats.json' is added to
                  report_stats['generated_files'].
  v16.9.0       — build_run_stats() is now called BEFORE the HTML report is
                  generated, and its return value is passed to
                  generate_html_report() as run_stats_data.  This supplies
                  the correct stage_05_scoring top-level fields (score_avg,
                  score_median, score_max, score_min) to the HTML generator,
                  fixing the avg/median = 0 display bug.
                — cfg is passed to generate_html_report() so that the new
                  Context section can read kernel.rev_old/rev_new and
                  artifact presence flags.
  v16.13.0      — serve_report.pyz generation: when html output is enabled,
                  lib.serve_script_gen.generate_serve_script() is called
                  after both HTML reports are written.  It packs the HTML
                  file(s) and all commits/*.json detail files into a
                  self-contained Python zipapp (ZIP archive with __main__.py
                  entry point).  Running that script starts an in-memory
                  HTTP server with no external file dependencies.
                  Generation failure is non-fatal (logged as a warning).
                  'serve_report.pyz' is added to generated_files on success.
  v16.14.0      — Filtered commits are now embedded in the unified
                  relevant_commits.html report via the filtered_commits kwarg
                  of generate_html_report().  The separate
                  filtered_commits.html file is no longer written.
                  filtered_commits.table.json is still written as a sidecar
                  for the JS layer.
  v18.1.0       — G.1: bulk JSON outputs use compact separators (',',':')
                  instead of indent=2 to reduce file sizes significantly.
                  Only per-commit shard files keep indent=2 for readability
                  in the HTML raw-tab.
                — G.2: _write_commit_details() now deduplicates makedirs
                  calls using a seen_dirs set; at most 16 mkdir calls for
                  the first-level bucket dirs (one per hex digit).
                — G.4: commit detail files are now stored as bucket JSON
                  files: commits/<sha[0]>/<sha[1:3]>.json  Each bucket file
                  is a dict keyed by full SHA.  This reduces the total number
                  of files from N (one per commit) to at most 256 (16x16
                  buckets), cutting inode pressure and serve_report.pyz
                  build time for large corpora.
  v18.2.0       — _rt_progress_f and _rt_finish_line_f are now module-level
                  variables so that tests can monkeypatch them reliably.
                  Previously they were local variables inside run(), making
                  monkeypatching impossible.
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
# Previously imported as local variables inside run(), which made
# monkeypatching via monkeypatch.setattr(_mod, '_rt_progress_f', ...) silently
# ineffective.
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
    """Build list-of-lists rows for CSV / XLSX / ODS output.

    Column order matches COMMIT_COLS:
      Rank | SHA | Subject | Author | Date | Score | Profiles | Profile Scores
                                                               | Product Evidence

    The Product Evidence cell is included here for tabular file formats
    (CSV/XLSX/ODS) because COMMIT_COLS includes it.  The HTML table uses
    a narrower column set that excludes Product Evidence — that exclusion
    is handled in html_report.py (_commit_row_html) per A.1 / D.16.
    """
    rows = []
    for c in commits:
        sc       = (c.get('scoring') or {})
        profiles = (sc.get('profiles') or {})
        prof_scores = '; '.join(
            '%s:%g' % (p, profiles.get(p, 0))
            for p in sorted(profiles)
        )
        stats = c.get('stats') or {}
        row = [
            c.get('_rank', ''),
            (c.get('commit') or '')[:12],
            c.get('subject', ''),
            c.get('author_org', ''),
            _fmt_date(c.get('author_time', '')),
            c.get('pick_priority', 0) or 0,
            c.get('score_norm', 0) or 0,
            c.get('backport_complexity', 0) or 0,
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
    """Write commit detail JSON files into bucket layout.

    G.4: Each commit is stored in commits/<sha[0]>/<sha[1:3]>.json
    where the file is a {sha: commit_data} dict.  At most 256 bucket
    files are ever created (16 first-level dirs x 16 second-level files).

    G.2: makedirs is deduplicated -- at most 16 mkdir calls.
    G.1: Bucket files are written with indent=2 for readability in the
         HTML raw-tab (these are the sidecar detail files, not bulk JSON).
    """
    if not commits:
        return 0
    os.makedirs(root, exist_ok=True)
    # Accumulate commits per bucket {bucket_file: (bucket_dir, {sha: data})}
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
    # Write each bucket file; deduplicate mkdir calls
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
            'matched_profiles': list(c.get('matched_profiles') or []),
        }
        if include_reason and c.get('_filter_reason', ''):
            row['_filter_reason'] = c.get('_filter_reason', '')
        rows.append(order_commit_details(row))
    _save_compact_json(path, rows)

# -- Per-profile statistics --------------------------------------------------

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


# -- Coverage metrics (promoted to report_stats) -----------------------------

def _coverage_metrics(scored):
    """Return diagnostic coverage counters included in report_stats.json.

    commits_matched_zero_profiles  -- commits that matched no profile at all
    commits_with_product_evidence  -- commits that have at least one
                                      product-evidence tag
    """
    return {
        'commits_matched_zero_profiles':
            sum(1 for c in scored if not (c.get('matched_profiles') or [])),
        'commits_with_product_evidence':
            sum(1 for c in scored if c.get('product_evidence')),
    }


def _build_evaluation_block(cfg, outputs, html_detail_mode, top_n, threshold):
    """A.4 / D.14: Build the evaluation metadata block for report_stats.

    This dict is stored in report_stats['evaluation'] and in
    report_metadata.json.  It is no longer rendered as a sidebar 'Parameters'
    section in the HTML left pane (removed in v16.9.0); instead the Context
    block in html_report._build_context() provides the relevant fields.
    """
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
    """G.1: Write data as compact JSON (no indentation, minimal separators).

    Used for bulk output files (relevant_commits.json, filtered_commits.json,
    rule_trace.json, profile_summary.json, profile_matrix.json, table sidecars)
    to reduce file sizes significantly for large corpora.
    """
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, default=str, separators=(',', ':'))
        f.write('\n')

# -- Output helpers ----------------------------------------------------------

def _resolve_outputs(cfg):
    """Return the set of output format names to produce.

    Reads ``reports.outputs`` list.  Recognised names: 'csv', 'html', 'xlsx', 'ods'.
    Default when not configured: {'csv', 'html'}.
    """
    reports   = cfg.get('reports', {}) or {}
    outputs_l = reports.get('outputs')

    if outputs_l is not None:
        return {str(o).lower() for o in (outputs_l or [])}

    # No outputs configured -- use default
    return {'csv', 'html'}


def _top_n(cfg):
    """Return the top-N limit, or None when top_n is 0 (meaning no limit)."""
    reports = cfg.get('reports', {}) or {}
    val = reports.get('top_n')
    if val is None:
        return 5000  # default
    n = int(val)
    return None if n == 0 else n  # 0 -> no limit


def _report_title(cfg):
    tmpl = cfg.get('reports', {}) or {}
    return tmpl.get('title', 'kcommit Analysis Report')


def _load_profile_rules_safe(cfg, cache):
    """Load profile rules, falling back to compiled_rules.json in cache.

    When load_profile_rules() raises (e.g. 'no active profiles configured')
    but a valid compiled_rules.json already exists in cache, inflate the
    cached on-disk schema into the in-memory form expected by scoring and
    return that instead.  This allows the report stage to run successfully
    after a prior pipeline run even if the active profiles config is empty.

    Returns an empty dict when neither source is available.
    """
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


# -- AI Analysis helpers -------------------------------------------------------

def _build_ai_analysis_schema():
    """Return the schema description for AI analysis input.
    
    This describes all fields available in each commit so the AI understands
    the context of the data it's analyzing.
    """
    return {
        'version': '1.0',
        'description': 'Schema for commits passed to AI for backport triage analysis',
        'fields': {
            'commit': {
                'type': 'string',
                'description': 'Full SHA-1 hash of the commit',
            },
            'subject': {
                'type': 'string',
                'description': 'Commit subject line (title)',
            },
            'author_name': {
                'type': 'string',
                'description': 'Name of the commit author',
            },
            'author_email': {
                'type': 'string',
                'description': 'Email address of the commit author',
            },
            'author_org': {
                'type': 'string',
                'description': 'Organization extracted from the email domain (e.g., "linuxfoundation.org" -> "linuxfoundation")',
            },
            'author_time': {
                'type': 'integer',
                'description': 'Unix timestamp of the commit date',
            },
            'body': {
                'type': 'string',
                'description': 'Full commit message body (excluding subject)',
            },
            'files': {
                'type': 'array',
                'description': 'List of file paths modified by this commit',
                'items': {'type': 'string'},
            },
            'stats': {
                'type': 'object',
                'description': 'Commit size indicators',
                'properties': {
                    'files_changed': {
                        'type': 'integer',
                        'description': 'Number of files modified by this commit',
                    },
                    'lines_changed': {
                        'type': 'integer',
                        'description': 'Total lines added + removed (commit churn)',
                    },
                    'hunks': {
                        'type': 'integer',
                        'description': 'Number of unified diff hunks (@@ blocks)',
                    },
                },
            },
            'meta': {
                'type': 'object',
                'description': 'Linux kernel commit annotation flags extracted from commit message',
                'properties': {
                    'is_fix': {
                        'type': 'boolean',
                        'description': 'True if commit message contains "Fixes:" tag (references another commit)',
                    },
                    'has_cve': {
                        'type': 'boolean',
                        'description': 'True if commit message mentions a CVE ID (e.g., CVE-2024-1234)',
                    },
                    'has_syzbot': {
                        'type': 'boolean',
                        'description': 'True if commit message mentions "syzbot" (syzkaller bug finder)',
                    },
                    'has_stable_cc': {
                        'type': 'boolean',
                        'description': 'True if commit message has "Cc: stable" tag (backport candidate)',
                    },
                },
            },
            'product_evidence': {
                'type': 'array',
                'description': 'List of product relevance evidence tags (why this commit impacts the product)',
                'items': {'type': 'string'},
            },
        },
    }


def _build_ai_analysis_input(cfg, prefilter_kept_commits, product_map):
    """Build the AI analysis input JSON structure.
    
    Returns a dict with metadata, schema, and commits ready for JSON serialization.
    The commits are the prefilter_kept commits (after prefilter, before scoring),
    with product_evidence computed but WITHOUT any scoring or backport indicators.
    """
    from lib.manifest import VERSION
    from lib.scoring import _collect_product_evidence
    import datetime
    
    commits_for_ai = []
    for c in prefilter_kept_commits:
        # Compute product_evidence for this commit
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
        # Python 3.6-3.7 fallback
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


def _write_ai_analysis_files(cfg, cache, outdir):
    """Write AI analysis input JSON and prompt template files.
    
    Returns list of paths written.
    """
    from lib.config import load_json
    from lib.manifest import CACHE_FILES
    
    written = []
    
    # Load prefilter_kept commits (after prefilter, before scoring/filtering)
    prefilter_kept = load_json(
        os.path.join(cache, CACHE_FILES['prefilter_kept']), default=[]
    ) or []
    
    # Load product_map to compute product_evidence
    product_map = load_json(
        os.path.join(cache, CACHE_FILES['product_map']), default={}
    ) or {}
    
    if not prefilter_kept:
        return written
    
    # Build and write AI analysis input JSON
    ai_input = _build_ai_analysis_input(cfg, prefilter_kept, product_map)
    ai_input_path = os.path.join(outdir, 'ai_analysis_input.json')
    _save_ordered_json(ai_input_path, ai_input)
    written.append(ai_input_path)
    
    # Write AI analysis prompt template
    prompt_path = os.path.join(outdir, 'ai_analysis_prompt.txt')
    with open(prompt_path, 'w', encoding='utf-8') as f:
        f.write(_get_ai_analysis_prompt())
    written.append(prompt_path)
    
    return written


def _get_ai_analysis_prompt():
    """Return the AI analysis prompt template as a string."""
    return '''# AI Analysis Prompt for kcommit-analysis-pipeline

## Task Overview

You are an expert Linux kernel analyst. Your task is to analyze commits that have
been identified as relevant to a specific embedded product (they modify code that
is built in the product) and provide recommendations on whether they should be
backported.

## Input Data

The input file `ai_analysis_input.json` contains:
- Commits that passed the prefilter (they modify what is built in the product)
- These are commits BEFORE any scoring or threshold filtering
- Each commit has metadata including subject, author, files changed, and annotation flags
- The `meta` field contains flags like `is_fix`, `has_cve`, `has_syzbot`, `has_stable_cc`
- The `product_evidence` field explains why the commit is relevant to the product
- NO scoring information (score, matched_profiles) or backport indicators (complexity, pick_priority) are included
- The AI should make its own independent assessment

## Analysis Requirements

For EACH commit, analyze the following:

### 1. Classification
Identify what type of change this is:
- `ai_is_security_fix`: Is this a security vulnerability fix?
- `ai_is_bug_fix`: Is this a bug fix (non-security)?
- `ai_is_performance_enhancement`: Does this improve performance?
- `ai_is_new_feature`: Is this adding a new feature?
- `ai_is_new_security_feature`: Is this adding a new security feature?

### 2. Risk Assessment (if NOT backported)
Identify the risks of NOT backporting this commit. Select all that apply:
- "security_vulnerability": The product would remain vulnerable to a security issue
- "system_stability": The product may experience crashes, hangs, or undefined behavior
- "data_corruption": Data could be corrupted or lost
- "performance_degradation": The product would have suboptimal performance
- "missing_feature": A useful/necessary feature would be missing
- "compliance_violation": The product would fail compliance requirements
- "none": No significant risk

### 3. Impact on Product
Assess how much this commit matters:
- `ai_impact_on_product`: "critical" | "high" | "medium" | "low" | "none"
- `ai_impact_description`: 1-2 sentences explaining the impact

### 4. Backport Effort Estimation
Estimate how difficult it would be to backport:
- `ai_backport_effort`: "very_easy" | "easy" | "moderate" | "hard" | "very_hard"
- `ai_backport_effort_reason`: Brief explanation (e.g., "simple one-line fix", 
  "touches many subsystems", "depends on newer kernel APIs")

### 5. CVE Information
- `ai_cve_ids`: Array of CVE IDs mentioned or relevant (empty array if none)

### 6. Recommendation
- `ai_backport_recommendation`: "strong_yes" | "yes" | "maybe" | "no" | "strong_no"
- `ai_summary`: 2-3 sentence summary explaining your recommendation

## Output Format

Return a JSON object with commit SHAs as keys:

{
  "<sha1>": {
    "ai_is_security_fix": true,
    "ai_is_bug_fix": false,
    "ai_is_performance_enhancement": false,
    "ai_is_new_feature": false,
    "ai_is_new_security_feature": false,
    "ai_risks_if_not_backported": ["security_vulnerability", "system_stability"],
    "ai_impact_on_product": "critical",
    "ai_impact_description": "Fixes a use-after-free vulnerability that could lead to privilege escalation",
    "ai_backport_effort": "easy",
    "ai_backport_effort_reason": "Isolated fix in a single function",
    "ai_cve_ids": ["CVE-2024-1234"],
    "ai_backport_recommendation": "strong_yes",
    "ai_summary": "This critical security fix addresses CVE-2024-1234. The vulnerability allows local privilege escalation. The fix is simple and self-contained, making it easy to backport."
  },
  "<sha2>": {
    ...
  }
}

## Guidelines

1. BE CONSERVATIVE: When uncertain about a classification, it's better to mark it as
   false or use "maybe" than to make an incorrect positive identification.

2. Use the `meta` flags as hints:
   - If `meta.has_cve` is true, there's likely a CVE to extract
   - If `meta.is_fix` is true, it's likely a bug or security fix
   - If `meta.has_stable_cc` is true, the upstream maintainers think it's worth backporting

3. Consider the `product_evidence` field:
   - This tells you WHY the commit is relevant to the product
   - Focus on commits with strong product relevance

4. For `ai_cve_ids`:
   - Extract CVE IDs from the commit message (look for CVE-YYYY-NNNN patterns)
   - Also infer CVEs from the description even if not explicitly mentioned
   - Return an empty array [] if no CVEs are found

5. For effort estimation:
   - "very_easy": 1-5 lines changed, single file, no API changes
   - "easy": <20 lines, few files, minimal dependencies
   - "moderate": 20-100 lines, multiple files, some dependencies
   - "hard": 100-500 lines, many files, significant dependencies
   - "very_hard": >500 lines, extensive changes, new APIs

6. For recommendation logic:
   - "strong_yes": Security fix + critical/high impact + easy/very_easy effort
   - "yes": Security fix OR high impact with reasonable effort
   - "maybe": Unclear benefit, medium/hard effort, or borderline impact
   - "no": Low impact + hard/very_hard effort
   - "strong_no": Breaking change, not applicable to product, or very high risk

## Example Output

{
  "abc123def456": {
    "ai_is_security_fix": true,
    "ai_is_bug_fix": true,
    "ai_is_performance_enhancement": false,
    "ai_is_new_feature": false,
    "ai_is_new_security_feature": false,
    "ai_risks_if_not_backported": ["security_vulnerability"],
    "ai_impact_on_product": "critical",
    "ai_impact_description": "Fixes a buffer overflow in the network stack that can be triggered remotely",
    "ai_backport_effort": "easy",
    "ai_backport_effort_reason": "Single function fix with clear boundaries",
    "ai_cve_ids": ["CVE-2024-5678"],
    "ai_backport_recommendation": "strong_yes",
    "ai_summary": "Critical security fix for CVE-2024-5678 addressing a remote buffer overflow. The fix is isolated and easy to backport. Strongly recommended."
  }
}
'''


# -- Stage entry point -------------------------------------------------------

def run(cfg, cache, outdir):
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
    _written = []  # every file actually written this run

    def _emit(path):
        """Record path as successfully written. Call AFTER the write."""
        try:
            _written.append(os.path.relpath(path, outdir))
        except ValueError:
            _written.append(path)

    def _update_stage7_progress(current, total, message):
        """A.3: write runtime_status.json AND call the TTY progress bar.

        The real update_stage_progress() signature is:
          update_stage_progress(index, stage_total, frac, label,
                                n_done=None, n_total=None)
        where:
          index       = this stage's 1-based position (7)
          stage_total = total number of stages (7)
          frac        = float 0.0-1.0 completion fraction
          label       = human-readable milestone string
          n_done      = current milestone number (optional)
          n_total     = total milestones (optional)

        v18.2.0: Uses module-level _rt_progress_f so tests can monkeypatch it.
        """
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

    # Stage counts for the hierarchical sidebar (D.12)
    _all_scored  = load_json(os.path.join(cache, CACHE_FILES['scored']), default=[]) or []
    _collected   = load_json(os.path.join(cache, CACHE_FILES['commits']), default=[]) or []
    _pf_kept     = load_json(os.path.join(cache, CACHE_FILES['prefilter_kept']), default=[]) or []
    _threshold   = (lambda filt: float(filt.get('min_score', 0) or 0))(cfg.get('filter', {}) or {})
    _scores_all  = [float(c.get('score', 0) or 0) for c in scored]

    report_stats = {
        # Stage 01 -- collection
        'st01_collected':           len(_collected),
        # Stage 04 -- prefilter
        'st04_prefilter_kept':      len(_pf_kept),
        'st04_prefilter_dropped':   len(_collected) - len(_pf_kept),
        # Stage 05 -- scoring
        'st05_total_scored':        len(_all_scored),
        # Stage 06 -- postfilter
        'st06_threshold':           _threshold,
        'st06_postfilter_dropped':  len(postfiltered),
        # Stage 07 -- report
        'total_scored_commits':     len(scored),
        'top_n':                    top_n,
        'score_highest':            max(_scores_all) if _scores_all else 0,
        'score_lowest':             min(_scores_all) if _scores_all else 0,
        'score_avg':                round(sum(_scores_all) / len(_scores_all), 1) if _scores_all else 0,
        **_coverage_metrics(scored),
        # A.4 / D.14: Evaluation block -- stored in report_stats.json and
        # report_metadata.json but no longer rendered as a sidebar section.
        'evaluation': _build_evaluation_block(
            cfg, outputs, html_detail_mode, top_n, _threshold),
    }
    prof_summary      = _profile_summary(scored, profile_rules)
    mat_hdr, mat_rows = _profile_matrix(scored)
    details_root = os.path.join(outdir, 'commits')
    _write_commit_details(details_root, list(scored) + list(filtered))

    # JSON outputs (always written) -- G.1: compact format for bulk files
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

    # Copy prefilter_debug.json from cache to outdir when it exists (v13.0.0)
    _pf_debug_src = os.path.join(cache, CACHE_FILES.get('prefilter_debug', 'prefilter_debug.json'))
    if os.path.exists(_pf_debug_src):
        _pf_debug_dst = os.path.join(outdir, 'prefilter_debug.json')
        shutil.copy2(_pf_debug_src, _pf_debug_dst)
        _emit(_pf_debug_dst)

    # rule_trace.csv -- only written when CSV output is enabled (v13.0.0)
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
    # CSV
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
        # Filtered-out commits
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
    # XLSX
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

    # ODS
    if 'ods' in outputs:
        if write_ods:
            try:
                write_ods(os.path.join(outdir, 'relevant_commits.ods'),
                          scored, prof_summary,
                          sheet_name='Relevant Commits')
                _emit(os.path.join(outdir, 'relevant_commits.ods'))
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

    # v16.9.0: build_run_stats() is now called BEFORE the HTML report so that
    # its return value (pipeline_run_stats dict with correct score_avg/median)
    # can be forwarded to generate_html_report() as run_stats_data.
    _update_stage7_progress(5, _STAGE7_MILESTONES, 'Building run statistics')
    run_stats_data = None
    try:
        _prs_path = os.path.join(outdir, CACHE_FILES['run_stats'])
        run_stats_data = build_run_stats(cfg, cache, outdir)
        _emit(_prs_path)
    except Exception as _e:
        logging.warning('pipeline_run_stats.json write failed: %s', _e)

    # HTML -- v16.14.0: filtered commits are passed via filtered_commits= into
    # the unified relevant_commits.html report.  No separate
    # filtered_commits.html is written.
    _update_stage7_progress(6, _STAGE7_MILESTONES, 'Writing report metadata sidecar')
    _hp = None  # set below; used later by serve_script_gen
    if 'html' in outputs:
        try:
            _save_ordered_json(os.path.join(outdir, 'report_metadata.json'), metadata)
            _emit(os.path.join(outdir, 'report_metadata.json'))
            _update_stage7_progress(7, _STAGE7_MILESTONES, 'Generating HTML report')
            _hp = os.path.join(outdir, 'relevant_commits.html')
            _tp = os.path.join(outdir, 'relevant_commits.table.json')
            _write_table_json(_tp, scored, include_reason=False)
            _emit(_tp)
            # Write filtered sidecar JSON so the JS tab can lazy-load it
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

        # v16.13.0 -- generate self-contained serve_report.pyz zipapp
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

    # Emit final progress milestone and terminate the TTY bar line
    _update_stage7_progress(_STAGE7_MILESTONES, _STAGE7_MILESTONES, 'Done')
    if _rt_finish_line_f is not None:
        try:
            _rt_finish_line_f()
        except Exception as _e:
            logging.debug('finish_progress_line (st07) failed: %s', _e)

    # AI Analysis: write input JSON and prompt template
    ai_written = _write_ai_analysis_files(cfg, cache, outdir)
    _written.extend(ai_written)
    
    # Embed generated_files list, then write report_stats.json last
    report_stats['generated_files'] = sorted(set(
        f for f in _written if f != 'report_stats.json'))
    save_json(os.path.join(outdir, 'report_stats.json'), report_stats)
    return report_stats
