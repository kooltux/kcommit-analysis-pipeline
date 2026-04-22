#!/usr/bin/env python3
# Generate CSV and JSON reports from the scored commit set.
from __future__ import print_function
import argparse
import csv
import os

from lib.config import load_config
from lib.io_utils import ensure_dir, load_json, save_json
from lib.validation import validate_inputs
from lib.pipeline_runtime import start_stage, finish_stage
from lib.html_report import generate_html_report


def main():
    # Parse arguments, validate inputs, and emit reviewer-friendly reports.
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    args = ap.parse_args()

    cfg = load_config(args.config)
    state_path = os.path.join(cfg.get('project', {}).get('work_dir', './work'), 'pipeline_state.json')
    started = start_stage(state_path, 'report_commits', 6, 6)

    problems, notices = validate_inputs(cfg)
    for note in notices:
        print(note)
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(2)

    work = cfg.get('project', {}).get('work_dir', './work')
    cache = os.path.join(work, 'cache')
    outdir = os.path.join(work, 'output')
    ensure_dir(outdir)

    scored = load_json(os.path.join(cache, 'scored_commits.json'), default=[]) or []
    scored = sorted(scored, key=lambda x: x.get('candidate_score', 0), reverse=True)

    # CSV and JSON reports for downstream consumers.
    with open(os.path.join(outdir, 'relevant_commits.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow([
            'commit',
            'subject',
            'product_score',
            'security_score',
            'performance_score',
            'stable_score',
            'candidate_score',
            'matched_profiles',
            'product_evidence',
        ])
        for c in scored:
            w.writerow([
                c.get('commit'),
                c.get('subject'),
                c.get('product_score'),
                c.get('security_score'),
                c.get('performance_score'),
                c.get('stable_score'),
                c.get('candidate_score'),
                ';'.join(c.get('matched_profiles', [])),
                ';'.join(c.get('product_evidence', [])),
            ])

    save_json(os.path.join(outdir, 'relevant_commits.json'), scored)

    profile_summary = {
        'profiles': dict((p, len(scored)) for p in cfg.get('active_profiles', [])),
        'overlaps': {','.join(cfg.get('active_profiles', [])): len(scored)} if cfg.get('active_profiles') else {},
    }
    save_json(os.path.join(outdir, 'profile_summary.json'), profile_summary)

    pipeline_state = load_json(os.path.join(work, 'pipeline_state.json'), default={}) or {}
    with_profiles = len([c for c in scored if c.get('matched_profiles')])
    without_profiles = len(scored) - with_profiles

    report_stats = {
        'total_commits_reported': len(scored),
        'commits_with_security_score': len([c for c in scored if c.get('security_score')]),
        'commits_with_performance_score': len([c for c in scored if c.get('performance_score')]),
        'commits_with_product_evidence': len([c for c in scored if c.get('product_evidence')]),
        'commits_with_any_profile': with_profiles,
        'commits_without_profile': without_profiles,
        'active_profiles': cfg.get('active_profiles', []),
        'template_options': cfg.get('templates', {}),
        'pipeline_state': pipeline_state,
    }
    save_json(os.path.join(outdir, 'report_stats.json'), report_stats)

    # Matrix of commit/profile pairs to aid visualization tooling.
    with open(os.path.join(outdir, 'profile_matrix.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['commit', 'profile'])
        for c in scored:
            for p in c.get('matched_profiles', []):
                w.writerow([c.get('commit'), p])

    # Optional HTML summary using templates when enabled in the configuration.
    html_path = None
    if cfg.get('templates', {}).get('html_summary', True):
        try:
            html_path = generate_html_report(work, cfg)
            print('HTML summary generated at %s' % html_path)
        except Exception as e:
            print('warning: failed to generate HTML summary: %s' % e)

    print('reports generated in %s' % outdir)
    finish_stage(
        state_path,
        'report_commits',
        started,
        status='ok',
        extra={
            'reported_commit_count': len(scored),
            'output_dir': outdir,
            'html_summary': bool(html_path),
        },
    )


if __name__ == '__main__':
    main()
