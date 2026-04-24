#!/usr/bin/env python3
"""Stage 05: Generate CSV, JSON, and HTML reports from scored commits.

"""
import csv
import os
import sys

from lib.io_utils import ensure_dir, load_json, save_json
from lib.pipeline_runtime import stage_main, get_pipeline_state
from lib.html_report import generate_html_report


def _profile_coverage(scored):
    zero   = sum(1 for c in scored if not (c.get('matched_profiles') or []))
    single = sum(1 for c in scored if len(c.get('matched_profiles') or []) == 1)
    multi  = sum(1 for c in scored if len(c.get('matched_profiles') or []) > 1)
    return {
        'commits_matched_zero_profiles':     zero,
        'commits_matched_one_profile':       single,
        'commits_matched_multiple_profiles': multi,
    }


@stage_main('report_commits', 4, 5)
def main(cfg, work):
    cache  = os.path.join(work, 'cache')
    outdir = os.path.join(work, 'output')
    ensure_dir(outdir)

    # Prefer JSONL for massive ranges (200k+), fallback to JSON
    jsonl_path = os.path.join(cache, 'scored_commits.jsonl')
    json_path  = os.path.join(cache, 'scored_commits.json')
    
    if os.path.exists(jsonl_path):
        from lib.io_utils import iter_jsonl
        # For reporting, we must sort, so we load into memory.
        # However, we only load relevant commits (score > 0) to save RAM.
        scored = []
        for c in iter_jsonl(jsonl_path):
            if c.get('score_total', 0) > 0:
                scored.append(c)
    else:
        scored = (load_json(json_path, default=[]) or [])
        scored = [c for c in scored if c.get('score_total', 0) > 0]

    scored = sorted(scored, key=lambda x: x.get('score_total', 0), reverse=True)

    # ── CSV report ────────────────────────────────────────────────────────
    csv_cols = [
        'commit', 'subject', 'author_name', 'author_time',
        'score_total', 'matched_profiles',
        'score_product', 'score_security', 'score_performance', 'score_stable',
        'evidence',
    ]
    csv_path = os.path.join(outdir, 'relevant_commits.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=csv_cols,
                                extrasaction='ignore')
        writer.writeheader()
        for c in scored:
            row = dict(c)
            row['matched_profiles'] = ';'.join(c.get('matched_profiles') or [])
            evidence = c.get('evidence', []) or []
            row['evidence'] = ';'.join([str(e) for e in evidence])
            sb = c.get('score_bonus', {}) or {}
            row['score_product']     = sb.get('product', 0)
            row['score_security']    = sb.get('security', 0)
            row['score_performance'] = sb.get('performance', 0)
            row['score_stable']      = sb.get('stable', 0)
            writer.writerow(row)

    # ── JSON reports ──────────────────────────────────────────────────────
    save_json(os.path.join(outdir, 'relevant_commits.json'), scored)

    # Richer profile summary: count + total_score per profile
    profile_summary = {}
    for c in scored:
        for p in (c.get('matched_profiles') or []):
            if p not in profile_summary:
                profile_summary[p] = {'count': 0, 'total_score': 0}
            profile_summary[p]['count']       += 1
            profile_summary[p]['total_score'] += c.get('score_total', 0) or 0
    save_json(os.path.join(outdir, 'profile_summary.json'), profile_summary)

    # Profile matrix CSV
    with open(os.path.join(outdir, 'profile_matrix.csv'), 'w',
                 newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['commit', 'subject', 'profile', 'score'])
        for c in scored:
            for p in (c.get('matched_profiles') or []):
                writer.writerow([
                    c.get('commit', ''),
                    c.get('subject', ''),
                    p,
                    c.get('score_profiles', {}).get(p, 0),
                ])

    # ── Stats ─────────────────────────────────────────────────────────────
    coverage = _profile_coverage(scored)
    active_profiles = list(
        ((cfg.get('profiles', {}) or {}).get('active')
         or cfg.get('active_profiles') or {})
    )
    tmpl_cfg = cfg.get('templates', {}) or {}

    state_path = os.path.join(work, 'pipeline_state.json')
    report_stats = {
        'total_scored_commits':            len(scored),
        'commits_with_security_score':     sum(
            1 for c in scored
            if (c.get('score_bonus', {}) or {}).get('security', 0) > 0),
        'commits_with_performance_score':  sum(
            1 for c in scored
            if (c.get('score_bonus', {}) or {}).get('performance', 0) > 0),
        'commits_with_stable_score':       sum(
            1 for c in scored
            if (c.get('score_bonus', {}) or {}).get('stable', 0) > 0),
        'commits_with_product_evidence':   sum(
            1 for c in scored if c.get('evidence')),
        'profile_coverage':                coverage,
        'active_profiles':                 active_profiles,
        'template_options':                tmpl_cfg,
        'pipeline_state':                  get_pipeline_state(state_path),
    }
    save_json(os.path.join(outdir, 'report_stats.json'), report_stats)

    # ── HTML report ───────────────────────────────────────────────────────
    html_path = None
    if tmpl_cfg.get('html_summary', True):
        try:
            html_path = generate_html_report(work, cfg)
            print('  HTML report: %s' % html_path)
        except Exception as e:
            print('  warning: HTML report generation failed: %s' % e)

    print('  reports generated in %s' % outdir)
    return {
        'reported_commit_count': len(scored),
        'profile_coverage':      coverage,
        'csv_path':              csv_path,
        'html_path':             html_path or '',
    }


if __name__ == '__main__':
    main()
