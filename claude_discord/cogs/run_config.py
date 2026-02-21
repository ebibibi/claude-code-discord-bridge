"""Configuration dataclass for Claude Code execution.

Bundles all parameters needed to execute Claude Code CLI and stream results
to a Discord thread. Using a dataclass instead of a long positional argument
list makes call sites more readable and extension safer (new fields can be
added without changing every caller).
"""

from __future__ import annotations

from dataclasses import dataclass

import discord

from ..claude.runner import ClaudeRunner
from ..concurrency import SessionRegistry
from ..database.ask_repo import PendingAskRepository
from ..database.lounge_repo import LoungeRepository
from ..database.repository import SessionRepository
from ..discord_ui.status import StatusManager


@dataclass
class RunConfig:
    """All parameters needed for a single Claude Code execution.

    Required fields:
        thread: Discord thread to post results to.
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
    """

    thread: discord.Thread
    runner: ClaudeRunner
    prompt: str
    session_id: str | None = None
    repo: SessionRepository | None = None
    status: StatusManager | None = None
    registry: SessionRegistry | None = None
    ask_repo: PendingAskRepository | None = None
    lounge_repo: LoungeRepository | None = None

    # Prevent accidental field mutation — RunConfig is a value object.
    # Use dataclasses.replace() to create modified copies.
    def __post_init__(self) -> None:
        if not self.prompt:
            raise ValueError("RunConfig.prompt must not be empty")

    def with_prompt(self, prompt: str) -> RunConfig:
        """Return a new RunConfig with a different prompt (immutable copy)."""
        from dataclasses import replace

        return replace(self, prompt=prompt)
