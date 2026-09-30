"""Add advisory AI findings to report outputs without touching scoring caches."""
import json
import os

from lib.ai_report import attach_ai_results, load_ai_results
from lib.config import load_json, save_json
from lib.manifest import CACHE_FILES
from lib.scoring import order_commit_details
from lib.stages import st07_report


def _write_json(path, data):
    with open(path, 'w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, separators=(',', ':'), default=str)
        stream.write('\n')


def run(cfg, cache, outdir):
    """Produce standard reports without regenerating the Stage 08 AI bundle."""
    old_writer = st07_report._write_ai_analysis_files
    st07_report._write_ai_analysis_files = lambda *_args, **_kwargs: []
    try:
        stats = st07_report.run(cfg, cache, outdir)
    finally:
        st07_report._write_ai_analysis_files = old_writer
    results = load_ai_results(outdir)
    if not results:
        return stats
    top_n = st07_report._top_n(cfg)
    relevant = load_json(os.path.join(cache, CACHE_FILES['relevant']), default=[]) or []
    if top_n is not None:
        relevant = relevant[:top_n]
    prefiltered = load_json(os.path.join(cache, CACHE_FILES['filtered']), default=[]) or []
    postfiltered = load_json(os.path.join(cache, CACHE_FILES['postfilter_dropped']), default=[]) or []
    relevant = attach_ai_results(relevant, results)
    filtered = attach_ai_results(prefiltered + postfiltered, results)
    _write_json(os.path.join(outdir, 'relevant_commits.json'),
                [order_commit_details(item) for item in relevant])
    if filtered:
        _write_json(os.path.join(outdir, 'filtered_commits.json'),
                    [order_commit_details(item) for item in filtered])
    st07_report._write_commit_details(os.path.join(outdir, 'commits'), relevant + filtered)
    if 'html' in st07_report._resolve_outputs(cfg):
        st07_report._write_table_json(os.path.join(outdir, 'relevant_commits.table.json'), relevant)
        if filtered:
            st07_report._write_table_json(os.path.join(outdir, 'filtered_commits.table.json'),
                                          filtered, include_reason=True)
        run_stats = load_json(os.path.join(outdir, CACHE_FILES['run_stats']), default=None)
        profile_summary = load_json(os.path.join(outdir, 'profile_summary.json'), default={}) or {}
        reports = cfg.get('reports') or {}
        detail_mode = reports.get('html_detail_mode', 'sidecar')
        html_path = os.path.join(outdir, 'summary.html')
        from lib.html_report import generate_html_report
        generate_html_report(
            relevant, profile_summary, stats, html_path,
            title=st07_report._report_title(cfg),
            templates_dir=cfg['paths'].get('templates_dir'),
            detail_mode=detail_mode,
            commit_index_path='./relevant_commits.table.json' if detail_mode == 'sidecar' else None,
            commit_detail_root='./commits',
            embed_compression=reports.get('html_embed_compression', 'none'),
            metadata_path='./report_metadata.json' if detail_mode == 'sidecar' else None,
            cfg=cfg, run_stats_data=run_stats,
            filtered_commits=filtered if filtered else None)
        from lib.serve_script_gen import generate_serve_script
        generate_serve_script(html_path=html_path,
                              commits_root=os.path.join(outdir, 'commits'),
                              output_path=os.path.join(outdir, 'serve_report.pyz'))
    stats['ai_analyzed_commits'] = len(results)
    save_json(os.path.join(outdir, 'report_stats.json'), stats)
    return stats
