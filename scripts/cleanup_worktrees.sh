#!/bin/bash
# Cleanup merged worktrees for ccdb
# Usage: ./scripts/cleanup_worktrees.sh [--dry-run]
#
# Checks each worktree's branch against GitHub PR status.
# Removes worktrees whose PRs are MERGED or CLOSED.
# Keeps worktrees for OPEN PRs and the main worktree.
#
# Run from repo root (auto-detected from script location)

set -euo pipefail

# Auto-detect repo root from script location.
# Uses `git rev-parse --show-toplevel` rather than `readlink -f` because BSD
# readlink (macOS) has no -f flag; git itself is already a hard dependency
# for this script (see the `gh`/`git worktree` calls below).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "[DRY RUN] No changes will be made."
    echo ""
fi

# Counters for summary
removed=0
kept=0
warned=0
errors=0

cd "$REPO_ROOT"

# Prune stale worktree references (dirs already deleted but git still tracks them)
if $DRY_RUN; then
    echo "[prune] Would run: git worktree prune"
else
    echo "[prune] Cleaning stale worktree references..."
    git worktree prune
fi

# Get main worktree path (first line of worktree list is always the main one)
main_worktree=$(git worktree list --porcelain | head -1 | sed 's/^worktree //')

echo ""
echo "Main worktree: $main_worktree"
echo "Scanning worktrees..."
echo ""

# Parse worktree list in porcelain format for reliable parsing
# Format: blocks separated by blank lines, each block has:
#   worktree /path
#   HEAD <sha>
#   branch refs/heads/<name>  (or "detached")
current_path=""
current_branch=""

while IFS= read -r line; do
    if [[ "$line" =~ ^worktree\ (.+) ]]; then
        current_path="${BASH_REMATCH[1]}"
        current_branch=""
    elif [[ "$line" =~ ^branch\ refs/heads/(.+) ]]; then
        current_branch="${BASH_REMATCH[1]}"
    elif [[ -z "$line" && -n "$current_path" ]]; then
        # End of block - process this worktree
        if [[ "$current_path" == "$main_worktree" ]]; then
            current_path=""
            current_branch=""
            continue
        fi

        # Protect active dev worktree — never remove the worktree registered
        # in ~/.ccdb-dev-worktree (used by `make dev-on` for local testing).
        DEV_WORKTREE_FILE="$HOME/.ccdb-dev-worktree"
        if [[ -f "$DEV_WORKTREE_FILE" ]]; then
            dev_worktree=$(cat "$DEV_WORKTREE_FILE" | tr -d '[:space:]')
            if [[ "$current_path" == "$dev_worktree" ]]; then
                echo "  [PROTECTED] Active dev worktree — skipping"
                kept=$((kept + 1))
                current_path=""
                current_branch=""
                continue
            fi
        fi

        if [[ -z "$current_branch" ]]; then
            echo "[WARN] $current_path: detached HEAD, no branch. Skipping."
            warned=$((warned + 1))
            current_path=""
            current_branch=""
            continue
        fi

        echo "--- Worktree: $current_path (branch: $current_branch)"

        # Check PR status via gh CLI
        pr_json=$(gh pr list --repo ebibibi/ebi-agent-chat-relay \
            --head "$current_branch" --state all --json state --limit 1 2>/dev/null || echo "[]")

        pr_state=$(echo "$pr_json" | jq -r '.[0].state // empty' 2>/dev/null || true)

        if [[ "$pr_state" == "MERGED" || "$pr_state" == "CLOSED" ]]; then
            echo "  PR state: $pr_state -> removing worktree and branch"
            if $DRY_RUN; then
                echo "  [DRY RUN] Would remove worktree: $current_path"
                echo "  [DRY RUN] Would delete branch: $current_branch"
            else
                # Remove worktree (--force handles uncommitted changes)
                if git worktree remove --force "$current_path" 2>/dev/null; then
                    echo "  Removed worktree: $current_path"
                else
                    echo "  [WARN] Worktree dir may already be gone, pruning..."
                    git worktree prune
                fi

                # Delete the local branch
                if git branch -D "$current_branch" 2>/dev/null; then
                    echo "  Deleted branch: $current_branch"
                else
                    echo "  [WARN] Branch $current_branch already deleted or not found"
                fi
            fi
            removed=$((removed + 1))

        elif [[ "$pr_state" == "OPEN" ]]; then
            echo "  PR state: OPEN -> keeping"
            kept=$((kept + 1))

        elif [[ -z "$pr_state" ]]; then
            echo "  [WARN] No PR found for branch '$current_branch'. Leftover branch?"
            echo "  Keeping worktree (manual review recommended)."
            warned=$((warned + 1))

        else
            echo "  [ERROR] Unexpected PR state: $pr_state"
            errors=$((errors + 1))
        fi

        echo ""
        current_path=""
        current_branch=""
    fi
done < <(git worktree list --porcelain; echo "")
# The trailing echo "" ensures the last block gets processed

echo "========================================="
echo "Summary:"
echo "  Removed:  $removed"
echo "  Kept:     $kept"
echo "  Warnings: $warned"
echo "  Errors:   $errors"
echo "========================================="

if $DRY_RUN && (( removed > 0 )); then
    echo ""
    echo "Run without --dry-run to actually clean up."
fi
