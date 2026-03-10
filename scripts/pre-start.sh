#!/bin/bash
# ccdb pre-start script — runs as ExecStartPre before bot process.
# Ensures code is at latest and dependencies are synced.
set -e

# Resolve the repository root dynamically so this script works for any user,
# regardless of where they cloned the repo.  Using readlink -f handles the case
# where the script itself is a symlink.
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
CCDB_HOME="$(dirname "$SCRIPT_DIR")"
cd "$CCDB_HOME"

# Locate uv: prefer the local installation, fall back to whatever is on PATH.
UV="${CCDB_UV_BIN:-}"
if [ -z "$UV" ]; then
    UV="$(command -v uv 2>/dev/null || true)"
fi
if [ -z "$UV" ]; then
    echo "[pre-start] ERROR: uv not found. Install it or set CCDB_UV_BIN." >&2
    exit 1
fi

# ── Webhook helper ──
DISCORD_WEBHOOK_URL=""
if [ -f .env ]; then
    DISCORD_WEBHOOK_URL=$(grep -E '^DISCORD_WEBHOOK_URL=' .env | cut -d'=' -f2- | tr -d '"' || true)
fi
send_webhook() {
    local message="$1"
    if [ -n "$DISCORD_WEBHOOK_URL" ]; then
        local escaped
        escaped=$(printf '%s' "$message" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')
        curl -s -o /dev/null -X POST "$DISCORD_WEBHOOK_URL" \
            -H "Content-Type: application/json" \
            -d "{\"content\": $escaped}" || echo "[pre-start] WARNING: webhook failed" >&2
    fi
}

# ── Step 1: Pull latest code (skip in local dev mode) ──
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
LOCAL_CHANGES=$(git status --porcelain 2>/dev/null)

if [ "$CURRENT_BRANCH" != "main" ] || [ -n "$LOCAL_CHANGES" ]; then
    echo "[pre-start] Local dev mode (branch: $CURRENT_BRANCH) — skipping git pull" >&2
else
    echo "[pre-start] Pulling latest code..." >&2
    set +e
    git pull --ff-only origin main 2>&1
    PULL_EXIT=$?
    set -e
    if [ $PULL_EXIT -ne 0 ]; then
        echo "[pre-start] WARNING: git pull failed (exit $PULL_EXIT), continuing with current code" >&2
    fi
fi

# ── Step 2: Sync dependencies ──
echo "[pre-start] Syncing dependencies..." >&2
"$UV" sync 2>&1

COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
echo "[pre-start] Code at: ${COMMIT}" >&2

# ── Step 2b: Dev worktree mode — override .pth to load code from worktree ──
# Create ~/.ccdb-dev-worktree (containing the worktree path) to activate dev mode.
# Use `make dev-on` / `make dev-off` in the worktree to manage this file.
DEV_WORKTREE_FILE="$HOME/.ccdb-dev-worktree"
if [ -f "$DEV_WORKTREE_FILE" ]; then
    DEV_WORKTREE=$(tr -d '[:space:]' < "$DEV_WORKTREE_FILE")
    if [ -d "$DEV_WORKTREE/claude_discord" ]; then
        echo "[pre-start] Dev worktree mode: loading claude_discord from $DEV_WORKTREE" >&2
        for pth in "$CCDB_HOME"/.venv/lib/python*/site-packages/_claude_code_discord_bridge.pth; do
            echo "$DEV_WORKTREE" > "$pth"
        done
    else
        echo "[pre-start] WARNING: $DEV_WORKTREE/claude_discord not found — using main tree" >&2
    fi
fi

# ── Step 3: Validate imports ──
echo "[pre-start] Validating imports..." >&2
set +e
IMPORT_ERROR=$(.venv/bin/python -c "from claude_discord.main import main" 2>&1)
IMPORT_EXIT=$?
set -e

if [ $IMPORT_EXIT -ne 0 ]; then
    echo "[pre-start] ERROR: Import validation failed:" >&2
    echo "$IMPORT_ERROR" >&2
    send_webhook "⚠️ **ccdb pre-start failed**: Import error.\n\`\`\`\n${IMPORT_ERROR}\n\`\`\`\nAttempting rollback..."

    echo "[pre-start] Rolling back..." >&2
    git revert --no-edit HEAD 2>&1 || git checkout HEAD~1 2>&1
    "$UV" sync 2>&1

    set +e
    ROLLBACK_ERROR=$(.venv/bin/python -c "from claude_discord.main import main" 2>&1)
    ROLLBACK_EXIT=$?
    set -e

    if [ $ROLLBACK_EXIT -ne 0 ]; then
        echo "[pre-start] FATAL: Import still fails after rollback" >&2
        send_webhook "🔴 **ccdb rollback also failed**.\n\`\`\`\n${ROLLBACK_ERROR}\n\`\`\`\nManual intervention required."
        exit 1
    fi

    send_webhook "✅ **ccdb rollback succeeded**: running on $(git rev-parse --short HEAD)."
fi

# ── Step 4: Cleanup stale worktrees ──
CLEANUP_SCRIPT="$CCDB_HOME/scripts/cleanup_worktrees.sh"
if [ -x "$CLEANUP_SCRIPT" ]; then
    "$CLEANUP_SCRIPT" 2>&1 || true
fi

echo "[pre-start] All checks passed. Starting bot (${COMMIT})." >&2
