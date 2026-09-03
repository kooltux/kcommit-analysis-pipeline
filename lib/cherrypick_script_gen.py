"""cherrypick_script_gen.py -- kcommit-analysis-pipeline v19.5.0

Copies a static, generic cherry-pick execution script plus a run-specific
JSON data file into the report output directory.

v19.5.0 design:
  - Script: cherry_pick.sh is a STATIC ASSET, resolved from
    cfg['paths']['assets_dir'] (default: <tool_root>/configs/assets,
    overridable via the "paths.assets_dir" config key, same convention as
    "reports.templates_dir"). It is copied byte-for-byte into output/
    (then chmod +x) -- never generated via string concatenation. It
    contains no run-specific data and can be edited/tested directly as an
    ordinary shell script; product configs may ship their own customized
    copy without touching the pipeline's own tree.
  - Data file: cherry_pick_data.json (generated, in output/) --
    {"target_rev": "...", "rev_new": "...",
     "commits": [{"sha": "...", "subject": "...", "relevant": true/false}, ...]}
  - Commits are sorted in git-history order (oldest -> newest).
  - The script takes --set=prefiltered or --set=relevant:
      --set=prefiltered: applies all commits (the big set)
      --set=relevant:    applies only commits with relevant=true (the small set)
  - The script embeds small Python snippets via `python3 - <<'PYEOF' ... PYEOF`
    heredocs with a QUOTED delimiter, so bash performs no expansion inside
    them; the data-file path and any other values are passed as real
    sys.argv entries, never interpolated into the Python source text. This
    avoids all bash/Python nested-quoting issues without needing a separate
    helper file.

Rationale:
  - Single source of truth for commit order (no duplication between two files)
  - Boolean flag is simpler than maintaining two separate arrays
  - output/ folder can be exported/archived independently from cache/
  - A copied static script is easier to review, diff, and shellcheck than
    one assembled from hundreds of string-joined lines
  - Resolving the asset via cfg['paths']['assets_dir'] (with the same
    default/override convention as templates_dir) lets product configs
    customize the script without forking the pipeline
"""
import os
import stat
import shutil
import json

from lib.config import load_json
from lib.manifest import CACHE_FILES, _ROOT_DIR
from lib.cherrypick_db import get_cherry_db_path, load_or_create_db
from lib.gitutils import list_rev_commits


# Fallback shipped asset, used when cfg['paths']['assets_dir'] is absent
# (e.g. hand-built cfg dicts in unit tests) -- mirrors the same default as
# lib/config.py's load_config() (<tool_root>/configs/assets).
_DEFAULT_ASSETS_DIR = os.path.join(_ROOT_DIR, 'configs', 'assets')
_ASSET_SCRIPT_PATH = os.path.join(_DEFAULT_ASSETS_DIR, 'cherry_pick.sh')


def _resolve_asset_script_path(cfg):
    """Return the cherry_pick.sh asset path for *cfg*.

    Prefers cfg['paths']['assets_dir'] (set by lib.config.load_config(),
    defaulting to the shipped configs/assets/ or a product-config override);
    falls back to the shipped default when 'paths' is absent or incomplete.
    """
    assets_dir = ((cfg.get('paths') or {}).get('assets_dir')) or _DEFAULT_ASSETS_DIR
    return os.path.join(assets_dir, 'cherry_pick.sh')


def _load_commits(cache, cache_key):
    """Return the raw commit dict list for *cache_key*, read once from disk."""
    return load_json(os.path.join(cache, CACHE_FILES[cache_key]), default=[]) or []


def _index_shas_and_subjects(commits):
    """Build (ordered deduped sha list, sha -> subject dict) in a single pass."""
    seen = set()
    shas = []
    subjects = {}
    for c in commits:
        if not isinstance(c, dict):
            continue
        sha = c.get('commit')
        if not sha:
            continue
        if sha not in seen:
            seen.add(sha)
            shas.append(sha)
            subjects[sha] = (c.get('subject') or '').replace('\n', ' ').strip()
    return shas, subjects


def _build_cherry_pick_data(cfg, cache):
    """Build the cherry-pick data structure for export.

    Returns:
        (data, stats) where data is a dict with:
          {'commits': [{'sha': str, 'subject': str, 'relevant': bool}, ...]}
        and stats is a dict with commit counts.
        Returns (None, stats) when nothing is available.
    """
    kernel  = cfg.get('kernel', {}) or {}
    collect = cfg.get('collect', {}) or {}

    target_rev = kernel.get('rev_old')
    cache_dir  = collect.get('cherry_pick_cache_dir')

    # Load both commit sets (prefilter_kept is primary, fall back to relevant if needed)
    prefiltered = _load_commits(cache, 'prefilter_kept')
    relevant = _load_commits(cache, 'relevant')

    # Build lookup for relevant commits
    relevant_shas = set(c.get('commit') for c in relevant if c.get('commit'))

    # Use prefilter_kept as primary source, fall back to relevant if empty
    all_commits = prefiltered if prefiltered else relevant

    # Index all commits
    all_shas, subjects = _index_shas_and_subjects(all_commits)

    stats = {
        'total_in_set':     len(all_shas),
        'tested':            0,
        'cherry_pickable':   0,
        'skipped_untested':  0,
        'skipped_conflict':  0,
        'prefiltered_count': 0,
        'relevant_count':    0,
    }

    if not all_shas or not target_rev or not cache_dir:
        stats['skipped_untested'] = len(all_shas)
        return None, stats

    db_path = get_cherry_db_path(cache_dir, target_rev)
    if not os.path.exists(db_path):
        stats['skipped_untested'] = len(all_shas)
        return None, stats

    db = load_or_create_db(cache_dir, target_rev)
    try:
        results = db.get_results(all_shas)
    finally:
        db.save()

    # Build commit list with relevant flag
    commit_list = []
    ok_shas = set()

    for sha in all_shas:
        result = results.get(sha)
        if result is None:
            stats['skipped_untested'] += 1
            continue
        stats['tested'] += 1
        if result.get('ok'):
            ok_shas.add(sha)
            is_relevant = sha in relevant_shas
            commit_list.append({
                'sha': sha,
                'subject': subjects.get(sha, ''),
                'relevant': is_relevant,
            })
            stats['cherry_pickable'] += 1
            if is_relevant:
                stats['relevant_count'] += 1
            else:
                stats['prefiltered_count'] += 1
        else:
            stats['skipped_conflict'] += 1

    if not commit_list:
        return None, stats

    # Re-derive authoritative oldest -> newest order from git history itself
    try:
        history_order = list_rev_commits(cfg)
    except Exception:
        history_order = all_shas

    # Filter to only ok_shas, preserving git-history order
    ordered_shas = [sha for sha in history_order if sha in ok_shas]

    # Safety net: include any ok_shas that history_order might have missed
    missing = [sha for sha in all_shas if sha in ok_shas and sha not in ordered_shas]
    ordered_shas.extend(missing)

    # Rebuild commit_list in correct order
    sha_to_commit = {c['sha']: c for c in commit_list}
    ordered_commits = [sha_to_commit[sha] for sha in ordered_shas if sha in sha_to_commit]

    return {'commits': ordered_commits}, stats


def write_cherry_pick_files(cfg, cache, outdir):
    """Copy cherry_pick.sh (static asset) and write cherry_pick_data.json
    to *outdir*.

    The asset is resolved from cfg['paths']['assets_dir'] (see
    _resolve_asset_script_path()), falling back to the pipeline's shipped
    configs/assets/cherry_pick.sh.

    Returns (script_path, data_path, stats) or (None, None, stats) when
    nothing is available to write.
    """
    data, stats = _build_cherry_pick_data(cfg, cache)

    if data is None:
        return None, None, stats

    # Embed target_rev / rev_new in the data file so the script is fully
    # self-contained (no need to read the pipeline config at runtime).
    kernel = cfg.get('kernel', {}) or {}
    data = dict(data)
    data['target_rev'] = kernel.get('rev_old')
    data['rev_new'] = kernel.get('rev_new')

    os.makedirs(outdir, exist_ok=True)

    # Write JSON data file
    data_path = os.path.join(outdir, 'cherry_pick_data.json')
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        f.write('\n')

    # Copy the static script asset verbatim (not generated)
    asset_path = _resolve_asset_script_path(cfg)
    script_path = os.path.join(outdir, 'cherry_pick.sh')
    shutil.copyfile(asset_path, script_path)

    try:
        st = os.stat(script_path)
        os.chmod(script_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP)
    except OSError:
        pass

    return script_path, data_path, stats
