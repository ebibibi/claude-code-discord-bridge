"""Shared helper for running Claude Code CLI and streaming results to a Discord thread.

Both ClaudeChatCog and SkillCommandCog need to run Claude and post results.
This module extracts that shared logic to avoid duplication.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from ..claude.runner import ClaudeRunner
from ..claude.types import MessageType, SessionState
from ..database.repository import SessionRepository
from ..discord_ui.chunker import chunk_message
from ..discord_ui.embeds import (
    error_embed,
    session_complete_embed,
    session_start_embed,
    tool_use_embed,
)
from ..discord_ui.status import StatusManager

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def run_claude_in_thread(
    thread: discord.Thread,
    runner: ClaudeRunner,
    repo: SessionRepository,
    prompt: str,
    session_id: str | None,
    status: StatusManager | None = None,
) -> str | None:
    """Execute Claude Code CLI and stream results to a Discord thread.

    Args:
        thread: Discord thread to post results to.
        runner: A fresh (cloned) ClaudeRunner instance.
        repo: Session repository for persisting thread-session mappings.
        prompt: The user's message or skill invocation.
        session_id: Optional session ID to resume. None for new sessions.
        status: Optional StatusManager for emoji reactions on the user's message.

    Returns:
        The final session_id, or None if the run failed.
    """
    state = SessionState(session_id=session_id, thread_id=thread.id)

    try:
        async for event in runner.run(prompt, session_id=session_id):
            # System message: capture session_id
            if event.message_type == MessageType.SYSTEM and event.session_id:
                state.session_id = event.session_id
                await repo.save(thread.id, state.session_id)
                if not session_id:
                    await thread.send(embed=session_start_embed(state.session_id))

            # Assistant message: text or tool use
            if event.message_type == MessageType.ASSISTANT:
                if event.text:
                    state.accumulated_text = event.text

                if event.tool_use:
                    if status:
                        await status.set_tool(event.tool_use.category)
                    embed = tool_use_embed(event.tool_use, in_progress=True)
                    msg = await thread.send(embed=embed)
                    state.active_tools[event.tool_use.tool_id] = msg

            # User message (tool result)
            if event.message_type == MessageType.USER and event.tool_result_id and status:
                await status.set_thinking()

            # Result: session complete
            if event.is_complete:
                if event.error:
                    await thread.send(embed=error_embed(event.error))
                    if status:
                        await status.set_error()
                else:
                    response_text = event.text or state.accumulated_text
                    if response_text:
                        for chunk in chunk_message(response_text):
                            await thread.send(chunk)

                    await thread.send(
                        embed=session_complete_embed(event.cost_usd, event.duration_ms)
                    )
                    if status:
                        await status.set_done()

                if event.session_id:
                    await repo.save(thread.id, event.session_id)
                    state.session_id = event.session_id

    except Exception:
        logger.exception("Error running Claude CLI for thread %d", thread.id)
        await thread.send(embed=error_embed("An unexpected error occurred."))
        if status:
            await status.set_error()

    return state.session_id
