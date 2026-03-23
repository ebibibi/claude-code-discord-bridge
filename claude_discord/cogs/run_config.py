"""Configuration dataclass for Claude Code execution.

Bundles all parameters needed to execute Claude Code CLI and stream results
to a Discord thread. Using a dataclass instead of a long positional argument
list makes call sites more readable and extension safer (new fields can be
added without changing every caller).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from ..claude.runner import ClaudeRunner
from ..claude.types import ImageData
from ..concurrency import SessionRegistry
from ..database.ask_repo import PendingAskRepository
from ..database.lounge_repo import LoungeRepository
from ..database.repository import SessionRepository
from ..discord_ui.status import StatusManager

if TYPE_CHECKING:
    from ..database.inbox_repo import ThreadInboxRepository
    from ..database.repository import UsageStatsRepository
    from ..discord_ui.thread_dashboard import ThreadStatusDashboard
    from ..discord_ui.views import StopView
    from ..worktree import WorktreeManager


@dataclass
class RunConfig:
    """All parameters needed for a single Claude Code execution.

    Required fields:
        thread: Discord thread (or text channel for inline-reply mode) to post results to.
        runner: A fresh (cloned) ClaudeRunner instance.
        prompt: The user's message or skill invocation.

    Optional fields:
        session_id: Session ID to resume. None for new sessions.
        repo: Session repository for persisting thread-session mappings.
              Pass None for automated workflows without session persistence.
        status: StatusManager for emoji reactions on the user's message.
        registry: SessionRegistry for concurrency awareness. When provided,
                  the session is registered during execution and a concurrency
                  notice is prepended to the prompt.
        ask_repo: Repository for persisting AskUserQuestion state across restarts.
        lounge_repo: Repository for AI Lounge context injection.
        stop_view: StopView instance to bump after each major message, keeping
                   the Stop button at the bottom of the thread.
        worktree_manager: WorktreeManager for automatic session worktree cleanup.
                          When provided, the worktree for this thread is removed
                          (if clean) after the session ends.
    """

    thread: discord.Thread | discord.TextChannel
    runner: ClaudeRunner
    prompt: str
    session_id: str | None = None
    repo: SessionRepository | None = None
    status: StatusManager | None = None
    registry: SessionRegistry | None = None
    ask_repo: PendingAskRepository | None = None
    lounge_repo: LoungeRepository | None = None
    stop_view: StopView | None = None
    worktree_manager: WorktreeManager | None = None
    # Base64-encoded image data for stream-json base64-type image blocks.
    images: list[ImageData] | None = None
    # When True, inject a system-prompt instruction telling Claude to write
    # requested file paths to .ccdb-attachments so the bot can send them.
    attach_on_request: bool = False
    # Thread inbox — when set, classifies the session's final message after
    # completion and persists the result so the dashboard can surface threads
    # that need the user's attention across bot restarts.
    inbox_repo: ThreadInboxRepository | None = None
    inbox_dashboard: ThreadStatusDashboard | None = None
    usage_repo: UsageStatsRepository | None = None
    claude_command: str = "claude"
    # When True, a compact guardrail was already injected into --append-system-prompt
    # for this run. Prevents infinite interrupt→rerun loops if compact fires again.
    post_compact_rerun: bool = False
    # When True, only text responses are shown to Discord. Tool embeds, thinking
    # blocks, session start/complete embeds, and other technical details are hidden.
    # Useful for public channels where non-technical users are watching.
    chat_only: bool = False

    # Prevent accidental field mutation — RunConfig is a value object.
    # Use dataclasses.replace() to create modified copies.
    def __post_init__(self) -> None:
        if not self.prompt and not self.images:
            raise ValueError("RunConfig.prompt must not be empty")

    def with_prompt(self, prompt: str) -> RunConfig:
        """Return a new RunConfig with a different prompt (immutable copy)."""
        from dataclasses import replace

        return replace(self, prompt=prompt)
