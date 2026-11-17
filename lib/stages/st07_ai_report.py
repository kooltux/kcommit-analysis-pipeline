"""Validate imported findings before the standard single-pass report stage."""
from lib.ai_report import load_ai_results
from lib.stages import st07_report


def run(cfg, cache, outdir):
    """Keep the normal no-AI path and never regenerate Stage 08 assets."""
    results = load_ai_results(outdir)
    if not results:
        return st07_report.run(cfg, cache, outdir)
    return st07_report.run(cfg, cache, outdir, results)
