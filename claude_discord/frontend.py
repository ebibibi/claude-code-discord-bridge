"""Discord as a whole frontend, not just one conversation.

:class:`~claude_discord.surface.DiscordSurface` is one thread. This is the
object that hands them out: the seam a scheduler, a webhook or the REST API
uses to reach a conversation *without knowing which platform it lives on*.

Why callers should not keep doing it themselves
-----------------------------------------------
``bot.get_channel(thread_id)`` appears all over the codebase, and each site
re-invents the same three decisions: fall back to ``fetch_channel`` when the
cache is cold, decide whether a non-thread channel is acceptable, and decide
what a missing thread means. They do not all decide the same way, and every one
of them is a place a Teams deployment would have to be patched.

Gathering them here means a scheduled task that resolves its follow-up thread
works on any frontend that implements the protocol — and, just as importantly,
that "the thread was deleted" is answered the same way everywhere: ``None``,
never an exception, because a deleted thread is ordinary and must not take a
scheduler loop down with it.

Contract
--------
This passes :func:`claude_code_core.conformance.check_frontend`, the same suite
a Teams frontend will have to pass. See ``tests/test_discord_frontend.py``.
"""

from __future__ import annotations

import contextlib
import logging

import discord
from discord.ext import commands

from claude_code_core.frontend import ThreadKey

from .database.frontend_thread_repo import FrontendThreadRepository
from .surface import DiscordSurface

logger = logging.getLogger(__name__)

__all__ = ["DiscordFrontend"]


class DiscordFrontend:
    """The running Discord bot, seen through the frontend protocol.

    Args:
        bot: The connected bot. Conversations are resolved from its cache
            first and fetched from the API only when the cache misses.
        ledger: Optional ``frontend_threads`` repository. Discord does not need
            it to function — its snowflake is already the key — but every
            conversation is recorded anyway, so a deployment that later gains a
            second frontend has one table that answers "where does this key
            live" for *all* of its conversations rather than half of them.
    """

    name = "discord"

    def __init__(
        self, bot: commands.Bot, *, ledger: FrontendThreadRepository | None = None
    ) -> None:
        self._bot = bot
        self._ledger = ledger

    async def start(self) -> None:
        """A no-op: the bot's own lifecycle is owned by ``setup_bridge``.

        The protocol has this method because a Teams frontend owns an HTTP
        listener it must bring up itself. Discord's does not, and pretending
        otherwise would give the caller two ways to start the same bot.
        """

    async def close(self) -> None:
        """A no-op, for the same reason as :meth:`start`."""

    async def resolve_surface(self, thread_key: ThreadKey) -> DiscordSurface | None:
        """Find an existing conversation, or ``None`` if it is gone.

        Discord snowflakes are used as thread keys verbatim, so no surrogate
        lookup is needed here — a Teams frontend will consult its
        ``frontend_threads`` mapping at this point instead.
        """
        channel = self._bot.get_channel(thread_key)
        if channel is None:
            with contextlib.suppress(discord.HTTPException, discord.NotFound, ValueError):
                channel = await self._bot.fetch_channel(thread_key)
        if not isinstance(channel, discord.Thread | discord.TextChannel):
            # Categories, forums, voice channels and stage channels are not
            # places a session can hold a conversation. So is a deleted thread,
            # which arrives here as None. Neither is recorded: a ledger entry
            # for a thread that does not exist is worse than a missing one.
            return None
        await self._record(channel)
        return DiscordSurface(channel)

    async def create_surface(self, *, parent_id: str, title: str) -> DiscordSurface:
        """Open a new conversation under a text channel.

        Raises:
            LookupError: if *parent_id* is not a text channel this bot can see.
                Unlike a missing thread, this is a configuration error — the
                caller asked for a channel that does not exist — so it is loud.
        """
        try:
            channel_id = int(parent_id)
        except (TypeError, ValueError) as exc:
            raise LookupError(f"parent_id must be a Discord channel id: {parent_id!r}") from exc

        channel = self._bot.get_channel(channel_id)
        if channel is None:
            with contextlib.suppress(discord.HTTPException, discord.NotFound):
                channel = await self._bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise LookupError(f"channel {channel_id} is not a text channel that supports threads")

        # A thread needs a starter message; the title doubles as its text so
        # the channel view shows what the conversation is for.
        starter = await channel.send(title[:2000])
        thread = await starter.create_thread(name=title[:100])
        await self._record(thread)
        return DiscordSurface(thread)

    async def _record(self, channel: discord.Thread | discord.TextChannel) -> None:
        """Note the conversation in the ledger. Never fatal.

        Bookkeeping must not be able to kill a session: if the write fails the
        conversation still works, and the next resolve will try again.
        """
        if self._ledger is None:
            return
        parent = getattr(channel, "parent_id", None)
        try:
            await self._ledger.register(
                self.name,
                str(channel.id),
                parent_external_id=str(parent) if parent is not None else None,
            )
        except Exception:
            logger.warning(
                "Could not record conversation %s in the ledger", channel.id, exc_info=True
            )
