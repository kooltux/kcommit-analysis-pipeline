#!/usr/bin/env bash
#
# cherry_pick.sh -- kcommit-analysis-pipeline generic cherry-pick executor
#
# This is a STATIC TEMPLATE, copied as-is from configs/assets/cherry_pick.sh
# into the report output directory. It contains no run-specific data --
# all commit data is read at runtime from cherry_pick_data.json, which sits
# next to this script.
#
# Usage:
#   ./cherry_pick.sh --set=prefiltered   # apply all commits (the big set)
#   ./cherry_pick.sh --set=relevant      # apply only relevant commits (the small set)
#   ./cherry_pick.sh --help              # show this help
#
# On conflict, git cherry-pick stops; resolve then run:
#   git cherry-pick --continue
# or abort the whole sequence with:
#   git cherry-pick --abort

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_FILE="$SCRIPT_DIR/cherry_pick_data.json"

# json_query() -- run a small Python snippet against $DATA_FILE.
# The snippet is passed via heredoc with a QUOTED delimiter ('PYEOF'), so
# bash performs NO variable expansion / quote interpretation inside it.
# The data-file path and any extra arguments are passed as real argv
# entries (sys.argv[1], sys.argv[2], ...), never interpolated into the
# Python source text. This sidesteps all bash/Python quote-escaping issues.
json_query() {
  local snippet="$1"; shift
  python3 - "$@" <<PYEOF
$snippet
PYEOF
}

# usage() -- display help and exit. Commit counts are computed on the fly
# from cherry_pick_data.json (never hardcoded).
usage() {
  local total=0 relevant=0 prefiltered_only=0
  if [[ -f "$DATA_FILE" ]]; then
    total=$(json_query '
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
print(len(d.get("commits", [])))
' "$DATA_FILE")
    relevant=$(json_query '
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
print(sum(1 for c in d.get("commits", []) if c.get("relevant")))
' "$DATA_FILE")
    prefiltered_only=$((total - relevant))
  fi

  cat <<EOF
Usage: cherry_pick.sh [OPTIONS]

Cherry-pick commits from a source revision onto a target revision.

Options:
  -h, --help           Show this help message and exit
  --set=SET            Commit set to apply:
                         "prefiltered" -- all commits that passed prefilter (the big set)
                         "relevant"    -- commits that scored above threshold (the small set)
  --git-dir PATH       Git repository directory (default: .)

Commit counts (from cherry_pick_data.json which contains only cherry-pickable commits):
  Total commits:    $total
  Relevant:         $relevant (scored above threshold)
  Prefiltered-only: $prefiltered_only (passed prefilter but below score threshold)

Data file: cherry_pick_data.json (must be in same directory as this script)
Log file:  cherry_pick.log
EOF
  exit 0
}

# ── Command-line parsing (getopt, for safety) ───────────────────────────
GIT_DIR="."
CHERRY_SET=""

OPTS=$(getopt -o h --long help,set:,git-dir: -n "cherry_pick.sh" -- "$@") || usage
eval set -- "$OPTS"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      ;;
    --set)
      CHERRY_SET="$2"
      shift 2
      ;;
    --git-dir)
      GIT_DIR="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Error: Unknown option: $1" >&2
      echo "" >&2
      usage
      ;;
  esac
done

if [[ -z "$CHERRY_SET" ]]; then
  echo "Error: --set argument is required" >&2
  echo "" >&2
  usage
fi

if [[ "$CHERRY_SET" != "prefiltered" && "$CHERRY_SET" != "relevant" ]]; then
  echo "Error: --set must be \"prefiltered\" or \"relevant\"" >&2
  echo "" >&2
  usage
fi

if ! git -C "$GIT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  echo "Error: GIT_DIR ($GIT_DIR) is not a git repository" >&2
  exit 1
fi

if [[ ! -f "$DATA_FILE" ]]; then
  echo "Error: Data file not found: $DATA_FILE" >&2
  exit 1
fi

# ── Load commits filtered by --set ───────────────────────────────
COMMITS=$(json_query '
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
want_relevant = sys.argv[2] == "relevant"
shas = [c["sha"] for c in data.get("commits", []) if (not want_relevant) or c.get("relevant")]
print(" ".join(shas))
' "$DATA_FILE" "$CHERRY_SET")

TOTAL=$(echo "$COMMITS" | wc -w)
if [[ "$TOTAL" -eq 0 ]]; then
  echo "No commits to apply for --set=$CHERRY_SET"
  exit 0
fi
echo "Found $TOTAL commits to cherry-pick"
echo ""

# ── Color helpers ──────────────────────────────────────────────────────
GREEN="\033[32m"
RED="\033[31m"
NC="\033[0m"

LOGFILE="cherry_pick.log"
rm -f "$LOGFILE"

CP_TMPFILE=$(mktemp)
trap 'rm -f "$CP_TMPFILE"' EXIT INT QUIT STOP

# cp_one() -- cherry-pick a single commit, print progress, log failures.
cp_one() {
  local sha="$1"
  local idx="$2"
  local total="$3"
  local subject="$4"
  if git -C "$GIT_DIR" cherry-pick "$sha" >"$CP_TMPFILE" 2>&1; then
    printf "${GREEN}Commit %s %s/%s - OK${NC}\n" "$sha" "$idx" "$total"
  else
    printf "${RED}Commit %s %s/%s - FAIL${NC}\n" "$sha" "$idx" "$total" >&2
    {
      echo "============================================================"
      echo "Commit: $sha  $subject"
      echo "Index:  $idx / $total"
      echo "Error output:"
      cat "$CP_TMPFILE"
      echo ""
    } >> "$LOGFILE"
  fi
}

# ── Checkout target rev, propose a working branch ─────────────────────────────────
TARGET_REV=$(json_query '
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
print(d.get("target_rev", "HEAD"))
' "$DATA_FILE")

echo "Checking out target rev: $TARGET_REV"
git -C "$GIT_DIR" checkout "$TARGET_REV" || { echo "Failed to checkout $TARGET_REV"; exit 1; }
echo ""

REV_NEW=$(json_query '
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
print(d.get("rev_new", "unknown"))
' "$DATA_FILE")

BRANCH_NAME="cherrypicking_from_$REV_NEW"
read -p "Create local branch $BRANCH_NAME before starting? [y/N] " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
  git -C "$GIT_DIR" checkout -b "$BRANCH_NAME" || { echo "Failed to create branch $BRANCH_NAME"; exit 1; }
  echo "Created and switched to branch: $BRANCH_NAME"
else
  echo "Skipping branch creation (on current branch: $(git -C "$GIT_DIR" branch --show-current))"
fi
echo ""

# ── Iterate and cherry-pick ──────────────────────────────────────────────────
IDX=0
for SHA in $COMMITS; do
  IDX=$((IDX + 1))
  SUBJECT=$(json_query '
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
sha = sys.argv[2]
subj = next((c.get("subject", "") for c in data.get("commits", []) if c.get("sha") == sha), "")
print(subj.replace("\n", " "))
' "$DATA_FILE" "$SHA")
  cp_one "$SHA" "$IDX" "$TOTAL" "$SUBJECT"
done

# ── Summary ────────────────────────────────────────────────────────────────────────
echo ""
if [[ -f "$LOGFILE" && -s "$LOGFILE" ]]; then
  fail_count=$(grep -c "^Commit:" "$LOGFILE" || echo 0)
  printf "${RED}%s commit(s) failed - see %s for details${NC}\n" "$fail_count" "$LOGFILE" >&2
else
  printf "${GREEN}All %d commits applied successfully${NC}\n" "$TOTAL"
fi
echo ""
