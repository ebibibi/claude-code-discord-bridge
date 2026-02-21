"""AskUserQuestion interaction handler.

Handles the full lifecycle of AskUserQuestion tool calls from Claude Code:
- Saving question state to DB for restart recovery
- Showing Discord buttons via AskView
- Waiting for user answers (up to 24 hours)
- Returning the formatted answer prompt for Claude to resume
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import discord

from ..claude.types import AskQuestion
from ..database.ask_repo import PendingAskRepository
from .ask_bus import ask_bus as _ask_bus
from .ask_view import AskView
from .embeds import ask_embed

logger = logging.getLogger(__name__)

# How long to wait for the user to answer (seconds).  24 hours lets users
# step away for the day and come back without "Interaction Failed" errors.
ASK_ANSWER_TIMEOUT = 86_400  # 24 h


async def collect_ask_answers(
    thread: discord.Thread,
    questions: list[AskQuestion],
    session_id: str,
    ask_repo: PendingAskRepository | None = None,
) -> str | None:
    """Show Discord UI for each question and return the formatted answer string.

    Processes questions sequentially (one at a time).  For each question:
    1. Saves it to the DB (for bot-restart recovery).
    2. Registers a Queue with ask_bus and shows the AskView.
    3. Awaits the answer for up to 24 hours via asyncio.wait_for.
    4. Cleans up the DB entry once answered or timed out.

    Returns a human-readable string to inject as the next human turn, or None
    if no question received an answer.
    """
    # Serialise questions once for DB storage.
    questions_dicts = [
        {
            "question": q.question,
            "header": q.header,
            "multi_select": q.multi_select,
            "options": [{"label": o.label, "description": o.description} for o in q.options],
        }
        for q in questions
    ]

    parts: list[str] = []
    for q_idx, q in enumerate(questions):
        # Persist so on_ready can re-register the view after a bot restart.
        if ask_repo is not None:
            await ask_repo.save(
                thread_id=thread.id,
                session_id=session_id,
                questions=questions_dicts,
                question_idx=q_idx,
            )

        # Register a waiter in the bus before showing the view so there is no
        # race between the user clicking and the queue being registered.
        answer_queue = _ask_bus.register(thread.id)

        view = AskView(q, thread_id=thread.id, q_idx=q_idx, ask_repo=ask_repo)
        msg = await thread.send(embed=ask_embed(q.question, q.header), view=view)

        try:
            selected = await asyncio.wait_for(answer_queue.get(), timeout=ASK_ANSWER_TIMEOUT)
        except TimeoutError:
            _ask_bus.unregister(thread.id)
            if ask_repo is not None:
                await ask_repo.delete(thread.id)
            # Remove buttons from the timed-out message so they stay inert.
            with contextlib.suppress(discord.HTTPException):
                await msg.edit(
                    content="-# ⏰ Question timed out — please send a new message to continue.",
                    embed=None,
                    view=None,
                )
            logger.info(
                "AskUserQuestion timed out after %ds for thread %d: %r",
                ASK_ANSWER_TIMEOUT,
                thread.id,
                q.question,
            )
            continue
        finally:
            _ask_bus.unregister(thread.id)

        if ask_repo is not None:
            await ask_repo.delete(thread.id)

        if not selected:
            continue

        answer_text = ", ".join(selected)
        parts.append(f"**{q.question}**\nAnswer: {answer_text}")

    if not parts:
        return None

    return (
        "[Response to AskUserQuestion]\n\n"
        + "\n\n".join(parts)
        + "\n\nPlease continue based on these answers."
    )
