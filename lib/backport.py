"""Backport-feasibility indicators for kcommit-analysis-pipeline.

These indicators are computed *beside* the profile/rule score and never feed
back into it (scoring stays exclusively rule-driven).  They exist to help a
human reviewer triage the relevant commits: which are cheap to cherry-pick,
which are painful, and which to look at first.

Three derived values are produced, all stored on the commit dict:

  score_norm          : int 0..100  (raw score normalized run-relative)
  backport_complexity : int 0..100  (higher = harder to cherry-pick)
  pick_priority       : int 0..100  (higher = look at this first)

The categorical backport *tier* was removed: the HTML report colours the
numeric backport_complexity directly via a shared 4-level heat scale computed
from the value, so a separate string bucket is redundant.

backport_complexity is a bounded, weighted blend of commit-shape signals that
correlate with cherry-pick difficulty:

    files_pts   (cap 25)  breadth  — more files → more context to re-match
    lines_pts   (cap 30)  volume   — total churn (insertions + deletions)
    hunks_pts   (cap 25)  fragmentation — scattered change blocks conflict more
    spread_pts  (cap 20)  cross-subsystem reach — distinct top-level dirs

    risk_raw = files_pts + lines_pts + hunks_pts + spread_pts        (0..100)

Then a "backport-friendliness" reduction is applied, because commits authored
to be backported (Cc: stable, Fixes:, CVE) tend to be small and self-contained:

    friendly  = min(25, 15*has_stable_cc + 10*is_fix + 5*has_cve)
    complexity = clamp(0, 100, round(risk_raw - friendly))

Merge commits are not simple cherry-picks → forced to 100.

The line/hunk/file terms use log2 saturation so a 10 000-line commit is not
100× a 100-line commit — past a point, "big is big".

pick_priority combines *relevance* (score_norm, the run-relative normalized
score) with *ease* (100 - complexity):

    score_norm    = round(100 * score / max_score_in_run)
    ease          = 100 - complexity
    pick_priority = round(0.70*score_norm + 0.30*ease)

Relevance dominates (0.70) so a critical-but-hard fix is never buried; ease
(0.30) floats the low-hanging fruit to the top of equally-relevant commits.
Because score_norm is normalized against the current run's maximum score, both
score_norm and pick_priority are *within-run* ranking aids and are not
comparable across runs.

Hard-coded weights are intentional (kept simple); they can be promoted to
config later if needed.
"""
import math

# -- backport_complexity weights (caps) ---------------------------------------
_CAP_FILES  = 25
_CAP_LINES  = 30
_CAP_HUNKS  = 25
_CAP_SPREAD = 20

# Saturation points: value at which a term reaches (near) its cap.
_SAT_FILES = 50
_SAT_LINES = 2000
_SAT_HUNKS = 60

# Friendliness bonuses (subtracted from risk); capped in aggregate.
_BONUS_STABLE = 15
_BONUS_FIX    = 10
_BONUS_CVE    = 5
_BONUS_CAP    = 25

# pick_priority blend weights (must sum to 1.0).
_W_RELEVANCE = 0.70
_W_EASE      = 0.30


def _log_saturate(value, cap, saturation):
    """Return cap * log2(1+value) / log2(1+saturation), clamped to [0, cap]."""
    if value <= 0:
        return 0.0
    pts = cap * math.log2(1 + value) / math.log2(1 + saturation)
    return max(0.0, min(float(cap), pts))


def _distinct_top_dirs(files):
    """Count distinct top-level directories touched (cross-subsystem spread).

    A file at repo root (no '/') is bucketed under '' so root-level changes do
    not each count as a separate subsystem.
    """
    tops = set()
    for f in files or []:
        if not f:
            continue
        head = str(f).split('/', 1)[0] if '/' in str(f) else ''
        tops.add(head)
    return len(tops)


def compute_backport_complexity(commit):
    """Compute backport complexity for a single commit dict.

    Reads commit['stats'] (files_changed, lines_changed, hunks), commit['meta']
    (is_fix/has_cve/has_stable_cc), commit['files'] (for cross-subsystem
    spread) and commit['parents'] (merge detection, when available).

    Returns a dict:
        {'complexity': int, 'factors': {...}}
    where factors exposes the per-term breakdown for transparency.
    """
    commit = commit or {}
    stats  = commit.get('stats') or {}
    meta   = commit.get('meta') or {}

    files_changed = int(stats.get('files_changed', 0) or 0)
    lines_changed = int(stats.get('lines_changed', 0) or 0)
    hunks         = int(stats.get('hunks', 0) or 0)
    spread        = _distinct_top_dirs(commit.get('files'))

    files_pts  = _log_saturate(files_changed, _CAP_FILES,  _SAT_FILES)
    lines_pts  = _log_saturate(lines_changed, _CAP_LINES,  _SAT_LINES)
    hunks_pts  = _log_saturate(hunks,         _CAP_HUNKS,  _SAT_HUNKS)
    spread_pts = min(_CAP_SPREAD, 5 * max(0, spread - 1))

    risk_raw = files_pts + lines_pts + hunks_pts + spread_pts

    friendly = 0
    if meta.get('has_stable_cc'):
        friendly += _BONUS_STABLE
    if meta.get('is_fix'):
        friendly += _BONUS_FIX
    if meta.get('has_cve'):
        friendly += _BONUS_CVE
    friendly = min(friendly, _BONUS_CAP)

    complexity = int(round(max(0.0, min(100.0, risk_raw - friendly))))

    parents  = commit.get('parents') or []
    is_merge = isinstance(parents, list) and len(parents) > 1
    if is_merge:
        complexity = 100

    factors = {
        'files_pts':  round(files_pts, 2),
        'lines_pts':  round(lines_pts, 2),
        'hunks_pts':  round(hunks_pts, 2),
        'spread_pts': round(float(spread_pts), 2),
        'risk_raw':   round(risk_raw, 2),
        'friendly':   friendly,
        'is_merge':   bool(is_merge),
        'distinct_top_dirs': spread,
    }
    return {
        'complexity': complexity,
        'factors':    factors,
    }


def normalize_score(score, max_score):
    """Return the run-relative normalized score as an int 0..100.

    score_norm = round(100 * score / max_score), with max_score clamped to >= 1
    so an all-zero run (or a single commit) never divides by zero.  This is the
    single source of truth for score normalization; both the 'Score %' report
    column and pick_priority's relevance term consume it.

    It is a *within-run* value (relative to this run's maximum score) and is
    not comparable across different runs.
    """
    max_score = max(float(max_score or 0), 1.0)
    norm = 100.0 * float(score or 0) / max_score
    return int(round(max(0.0, min(100.0, norm))))


def compute_pick_priority(score_norm, complexity):
    """Combine relevance (score_norm) and ease (100 - complexity) into 0..100.

    *score_norm* is the already-normalized 0..100 relevance value produced by
    normalize_score() — reused here so normalization happens exactly once.
    Returns an int 0..100.
    """
    rel  = max(0.0, min(100.0, float(score_norm or 0)))
    ease = max(0.0, min(100.0, 100.0 - float(complexity or 0)))
    priority = _W_RELEVANCE * rel + _W_EASE * ease
    return int(round(max(0.0, min(100.0, priority))))


def enrich_commit_backport(commit, max_score):
    """Attach score_norm, backport_complexity and pick_priority to *commit*.

    Mutates and returns the commit dict.  Also stores a 'backport' sub-dict
    with the factor breakdown for diagnostics / detail views.
    """
    result = compute_backport_complexity(commit)
    complexity = result['complexity']
    commit['backport_complexity'] = complexity
    commit['backport']            = {
        'complexity': complexity,
        'factors':    result['factors'],
    }
    commit['score_norm'] = normalize_score(commit.get('score', 0), max_score)
    commit['pick_priority'] = compute_pick_priority(
        commit['score_norm'], complexity)
    return commit
