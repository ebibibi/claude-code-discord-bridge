"""Docs Sync — ccdb WebhookTriggerCog configuration for auto-documentation.

Two modes:
- "docs-sync" (normal push): English docs sync + Japanese translation only
- "docs-sync-translate" (release): Full multi-language translation

This file is prompt/config-only.  Execution logic lives in ccdb's WebhookTriggerCog.

Usage:
    CUSTOM_COGS_DIR=examples/ebibot/cogs ccdb start
"""

from __future__ import annotations

import os

from claude_discord.cogs.headless_backend import (
    backend_factory_from_components,
    backend_settings_from_components,
)
from claude_discord.cogs.webhook_trigger import WebhookTrigger, WebhookTriggerCog

_COMMON_HEADER = """\
You are a documentation maintainer for the claude-code-discord-bridge project.
The repository is at /home/ebi/claude-code-discord-bridge.

CRITICAL: NEVER use `git checkout` or `git switch` in the main working directory.
All doc changes MUST be made in a git worktree to avoid disrupting other sessions.

## Step 1: Pull latest and create a worktree

```bash
cd /home/ebi/claude-code-discord-bridge && git pull origin main
BRANCH_NAME="docs-sync/$(date +%Y%m%d-%H%M%S)"
WORKTREE_DIR="/tmp/ccdb-docs-sync-$$"
git worktree add -b "$BRANCH_NAME" "$WORKTREE_DIR" HEAD
```

From this point on, all file reads and edits happen in
`$WORKTREE_DIR`, NOT in the main repo directory.
You may read files from the main repo for reference, but NEVER write to it.

## Step 2: Analyze what changed

```bash
cd /home/ebi/claude-code-discord-bridge && git diff HEAD~1 HEAD --stat && git diff HEAD~1 HEAD
```

## Step 3: Update English documentation if needed

Work in the worktree directory (`$WORKTREE_DIR`).

If **source code** (.py files) changed:
- Read the changed code and check if README.md or CONTRIBUTING.md need updates
- Update sections about features, architecture, configuration, etc. if the code changes affect them
- Keep documentation accurate and in sync with the code
- Do NOT update docs for trivial changes (formatting, comments, internal refactors)
"""

_TRANSLATE_JA_STEP = """

## Step 4: Translate to Japanese

Update or create Japanese translations in `docs/ja/`
for each English doc (README.md, CONTRIBUTING.md).

Translation rules:
1. Keep all markdown formatting, code blocks, links, and badges intact
2. Do NOT translate: code snippets, URLs, file paths, variable names, common English tech terms
3. DO translate: headings, descriptions, explanatory text, table headers/descriptions
4. Add a bilingual notice at the top
5. Use natural, fluent Japanese
6. Update relative links to point to Japanese versions where they exist
"""

_TRANSLATE_FULL_STEP = """

## Step 4: Translate to all supported languages

Target languages (create docs/{lang}/ for each):
- `ja` -- Japanese
- `zh-CN` -- Chinese Simplified
- `ko` -- Korean
- `es` -- Spanish
- `pt-BR` -- Portuguese (Brazil)
- `fr` -- French

Translation rules:
1. Keep all markdown formatting, code blocks, links, and badges intact
2. Do NOT translate: code snippets, URLs, file paths, variable names, common English tech terms
3. DO translate: headings, descriptions, explanatory text
4. Add a bilingual notice at the top of each translated file
5. Use natural, fluent language
"""

_PR_STEP_SYNC = """

## Step 5: Create a PR with auto-merge

If any documentation files were changed in the worktree:

1. Commit and push from the worktree:
```bash
cd "$WORKTREE_DIR"
git add -A
git commit -m "[docs-sync] Update documentation (English + Japanese)"
git push -u origin HEAD
```

2. Create PR with bilingual summary and enable auto-merge:
```bash
gh pr create --title "[docs-sync] Update documentation" --body-file /tmp/docs-sync-pr-body.md
gh pr merge --auto --squash
```

## Step 6: Clean up worktree

```bash
cd /home/ebi/claude-code-discord-bridge && git worktree remove "$WORKTREE_DIR"
```
"""

_PR_STEP_TRANSLATE = """

## Step 5: Create a PR with auto-merge

If any files were changed in the worktree:

1. Commit and push from the worktree:
```bash
cd "$WORKTREE_DIR"
git add -A
git commit -m "[docs-sync] Update documentation and translations"
git push -u origin HEAD
```

2. Create PR with bilingual summary and enable auto-merge:
```bash
gh pr create --title "[docs-sync] Update documentation and translations" \
  --body-file /tmp/docs-sync-pr-body.md
gh pr merge --auto --squash
```

## Step 6: Clean up worktree

```bash
cd /home/ebi/claude-code-discord-bridge && git worktree remove "$WORKTREE_DIR"
```
"""

DOCS_SYNC_PROMPT = _COMMON_HEADER + _TRANSLATE_JA_STEP + _PR_STEP_SYNC
DOCS_TRANSLATE_PROMPT = _COMMON_HEADER + _TRANSLATE_FULL_STEP + _PR_STEP_TRANSLATE

BRIDGE_DIR = os.getenv("CCDB_REPO_DIR", os.path.expanduser("~/claude-code-discord-bridge"))

DOCS_SYNC_TRIGGERS = {
    "\U0001f504 docs-sync-translate": WebhookTrigger(
        prompt=DOCS_TRANSLATE_PROMPT,
        working_dir=BRIDGE_DIR,
        timeout=900,
    ),
    "\U0001f504 docs-sync": WebhookTrigger(
        prompt=DOCS_SYNC_PROMPT,
        working_dir=BRIDGE_DIR,
        timeout=300,
    ),
}


async def setup(bot: object, runner: object, components: object) -> None:
    """Entry point for the custom Cog loader."""
    # Determine channel IDs for the webhook trigger
    channel_id = getattr(bot, "channel_id", None)
    channel_ids = {channel_id} if channel_id else set()

    # Also check for CLAUDE_CHANNEL_ID env var
    env_channel = os.getenv("CLAUDE_CHANNEL_ID", "")
    if env_channel.isdigit():
        channel_ids.add(int(env_channel))

    cog = WebhookTriggerCog(
        bot=bot,  # type: ignore[arg-type]
        runner=runner,  # type: ignore[arg-type]
        triggers=DOCS_SYNC_TRIGGERS,
        channel_ids=channel_ids or None,
        backend_factory=backend_factory_from_components(components),
        backend_settings=backend_settings_from_components(components),
    )
    await bot.add_cog(cog)  # type: ignore[union-attr]
