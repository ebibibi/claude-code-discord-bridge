#!/usr/bin/env bash
# Report whether the running bot is loading code that is not on origin/main.
#
# `make dev-on` writes ~/.ccdb-dev-worktree, and the import hook installed by
# pre-start.sh then redirects claude_discord / claude_code_core to that
# worktree. It is the right tool for testing a change against real Discord
# traffic, but nothing expires it: pre-start.sh prints one line at boot and
# never mentions it again, so a forgotten `make dev-on` keeps a side branch in
# production indefinitely while every merged PR appears to deploy and does not.
#
# Exit codes:
#   0  main-tree mode, or dev mode on code already merged to origin/main
#   1  dev mode on code that is NOT on origin/main  (drift)
#   2  dev mode configured but unusable (marker points nowhere)
set -u

CCDB_HOME="${CCDB_HOME:-$HOME/claude-code-discord-bridge}"
MARKER="$HOME/.ccdb-dev-worktree"

if [ ! -f "$MARKER" ]; then
    echo "OK: main-tree mode (no $MARKER)"
    exit 0
fi

WORKTREE="$(cat "$MARKER" 2>/dev/null | tr -d '[:space:]')"
if [ -z "$WORKTREE" ] || [ ! -d "$WORKTREE/claude_discord" ]; then
    echo "BROKEN: $MARKER points to '$WORKTREE', which has no claude_discord/."
    echo "        The import hook silently falls back to the main tree."
    exit 2
fi

# Age of the marker is the honest measure of "how long has this been on".
MARKER_EPOCH="$(stat -c %Y "$MARKER" 2>/dev/null || echo 0)"
NOW_EPOCH="$(date +%s)"
DAYS=$(( (NOW_EPOCH - MARKER_EPOCH) / 86400 ))

BRANCH="$(git -C "$WORKTREE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
HEAD_SHA="$(git -C "$WORKTREE" rev-parse --short HEAD 2>/dev/null || echo '?')"

# Compare against the remote's idea of main, not a local ref that may itself be
# stale — the whole point is to detect "main moved and production did not".
git -C "$CCDB_HOME" fetch -q origin main 2>/dev/null || true
BEHIND="$(git -C "$CCDB_HOME" rev-list --count "$HEAD_SHA"..origin/main 2>/dev/null || echo '?')"

if git -C "$CCDB_HOME" merge-base --is-ancestor "$HEAD_SHA" origin/main 2>/dev/null; then
    echo "OK: dev mode on $BRANCH ($HEAD_SHA), already merged to origin/main."
    echo "    Behind origin/main by $BEHIND commit(s); on for ${DAYS}d."
    exit 0
fi

cat <<REPORT
DRIFT: the bot is running code that is not on origin/main.

  worktree : $WORKTREE
  branch   : $BRANCH ($HEAD_SHA)
  merged   : NO — $HEAD_SHA is not an ancestor of origin/main
  behind   : $BEHIND commit(s) of origin/main are NOT running
  dev mode : on for ${DAYS} day(s) (marker mtime)

Every PR merged in that window looks deployed and is not. Either finish the
branch (open a PR and merge it) or run 'make dev-off' to return to main.

Before switching, check .env for values only the dev branch understands — a
setting the main tree cannot parse falls back to a default, which changes
behaviour without erroring.
REPORT
exit 1
