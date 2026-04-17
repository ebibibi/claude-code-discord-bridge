#!/usr/bin/env bash
# Build a standalone claude-code-core wheel.
#
# The core package lives in the ccdb monorepo but can be installed
# independently (e.g. by Teams Bot) without pulling in discord.py.
#
# Usage:
#   ./scripts/build-core-wheel.sh          # → dist/claude_code_core-*.whl
#   ./scripts/build-core-wheel.sh 0.2.0    # → dist/claude_code_core-0.2.0-*.whl
#
# The wheel is placed in ./dist/ alongside the ccdb wheel (if any).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="${1:-0.1.0}"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# Copy the core package source
cp -r "$REPO_ROOT/claude_code_core" "$TMPDIR/claude_code_core"
# Remove __pycache__
find "$TMPDIR" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true

# Write a standalone pyproject.toml
cat > "$TMPDIR/pyproject.toml" << EOF
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "claude-code-core"
version = "$VERSION"
description = "Frontend-agnostic core library for Claude Code CLI integration"
license = {text = "MIT"}
requires-python = ">=3.10"
dependencies = [
    "aiosqlite>=0.20,<1.0",
]

[tool.hatch.build.targets.wheel]
packages = ["claude_code_core"]
EOF

# Build using uv (available in the repo's venv)
cd "$TMPDIR"
uv build --wheel 2>/dev/null || python -m build --wheel

# Copy wheel to repo dist/
mkdir -p "$REPO_ROOT/dist"
cp "$TMPDIR/dist"/*.whl "$REPO_ROOT/dist/"

echo ""
echo "✅ Built: $(ls "$REPO_ROOT/dist"/claude_code_core-*.whl)"
