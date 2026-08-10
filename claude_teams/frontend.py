"""Teams as a whole frontend — the object that hands conversations out.

:class:`~claude_teams.surface.TeamsSurface` is one conversation. This is the
seam a scheduler, a webhook or the REST API uses to reach one *without knowing
which platform it lives on*, and it is what makes a Teams deployment reachable
by everything ccdb already does rather than only by people typing into it.

The awkward part: an address is two things
------------------------------------------
Discord needs one id to post anywhere. Teams needs the conversation id **and**
the regional Bot Connector that owns it, and only the second is missing from
the ledger — which stores where a conversation is, not which host serves it.

So this class learns ``serviceUrl`` from inbound traffic and keeps it, and a
deployment can configure the one its tenant uses. Without either, a conversation
resolves to ``None``: knowing a conversation exists and not where to post to it
is not a surface, and inventing a host would send a session's output somewhere
nobody is reading.

Contract
--------
Passes :func:`claude_code_core.conformance.check_frontend`, the same suite
``DiscordFrontend`` passes. See ``tests/test_teams_frontend.py``.
"""

from __future__ import annotations

import logging
from typing import Any

from claude_code_core.frontend import ThreadKey

from .capabilities import TEAMS_CAPABILITIES
from .conversation import ConversationRef
from .files import FileTransferRegistry
from .interactions import InteractionRegistry
from .surface import TEAMS_FRONTEND, TeamsSurface

logger = logging.getLogger(__name__)

__all__ = ["TeamsFrontend"]


class TeamsFrontend:
    """The running Teams app, seen through the frontend protocol.

    Args:
        connector: Something with ``send_activity`` / ``update_activity``.
        ledger: The ``frontend_threads`` repository. Teams *needs* it in a way
            Discord does not: its conversation ids are strings, the ThreadKey
            is a hash of one, and a hash does not run backwards. Without the
            ledger a deployment can look up a session and have no way to reply
            to it.
        create_conversation: ``async (parent_id, title, service_url) -> str``
            returning the new conversation id. Injected because starting a
            conversation is the one operation that differs between a channel
            and a group chat, and a deployment may need to route it through
            its own client. :meth:`BotConnector.create_conversation` is the
            stock implementation.
        default_service_url: The Bot Connector host to use for a conversation
            this process has not heard from since it started. A tenant's is
            stable, so configuring it is what lets a scheduled follow-up post
            after a restart.
    """

    name = TEAMS_FRONTEND

    def __init__(
        self,
        connector: Any,
        ledger: Any,
        *,
        create_conversation: Any = None,
        default_service_url: str | None = None,
        interactions: InteractionRegistry | None = None,
        files: FileTransferRegistry | None = None,
    ) -> None:
        self._connector = connector
        self._ledger = ledger
        self._create_conversation = create_conversation
        self._default_service_url = default_service_url
        self._interactions = interactions or InteractionRegistry()
        self._files = files or FileTransferRegistry()
        self._service_urls: dict[str, str] = {}

    @property
    def interactions(self) -> InteractionRegistry:
        return self._interactions

    @property
    def files(self) -> FileTransferRegistry:
        return self._files

    async def start(self) -> None:
        """Nothing to connect: the transport is inbound HTTP, not a socket."""

    async def close(self) -> None:
        """Nothing to disconnect, for the same reason."""

    def remember(self, conversation_id: str, service_url: str) -> None:
        """Record where a conversation is served from.

        Called for every inbound activity. This is how a deployment with no
        configured default can still post into a conversation later in the
        same process — and why one *with* a default keeps working across a
        restart.
        """
        if conversation_id and service_url:
            self._service_urls[conversation_id] = service_url

    async def resolve_surface(self, thread_key: ThreadKey) -> TeamsSurface | None:
        """Find an existing conversation, or ``None``.

        ``None`` covers three different things on purpose — no ledger entry,
        an entry belonging to another frontend, and an entry with no known
        host — because every caller does the same thing with all three, and a
        scheduler loop must not be taken down by any of them.
        """
        entry = await self._ledger.resolve(thread_key)
        if entry is None or entry.frontend != self.name:
            return None
        service_url = self._service_url_for(entry.external_id)
        if service_url is None:
            logger.warning(
                "No serviceUrl known for Teams conversation %s; set CCDB_TEAMS_SERVICE_URL "
                "so scheduled posts survive a restart",
                entry.external_id,
            )
            return None
        return self._surface(
            thread_key,
            ConversationRef(
                service_url=service_url,
                conversation_id=entry.external_id,
                conversation_type=_type_of(entry.external_id),
            ),
        )

    async def create_surface(self, *, parent_id: str, title: str) -> TeamsSurface:
        """Start a new conversation under a channel and register its key.

        In a channel this is a new reply chain, which is what keeps ccdb's
        Thread=Session rule intact on a platform whose "threads" are a
        property of a message rather than an object of their own.
        """
        if self._create_conversation is None:
            raise LookupError(
                "this Teams frontend cannot start conversations — no create_conversation given"
            )
        service_url = self._service_url_for(parent_id)
        if service_url is None:
            raise LookupError(f"no serviceUrl known for {parent_id!r}; set CCDB_TEAMS_SERVICE_URL")

        conversation_id = await self._create_conversation(parent_id, title, service_url)
        if not conversation_id:
            raise LookupError(f"Teams did not return a conversation id for {parent_id!r}")

        self.remember(conversation_id, service_url)
        thread_key = await self._ledger.register(
            self.name, conversation_id, parent_external_id=parent_id
        )
        return self._surface(
            thread_key,
            ConversationRef(
                service_url=service_url,
                conversation_id=conversation_id,
                conversation_type=_type_of(conversation_id),
            ),
            title=title,
        )

    # -- internals ---------------------------------------------------------

    def _service_url_for(self, conversation_id: str) -> str | None:
        return self._service_urls.get(conversation_id) or self._default_service_url

    def _surface(
        self, thread_key: ThreadKey, ref: ConversationRef, *, title: str = "Session"
    ) -> TeamsSurface:
        return TeamsSurface(
            thread_key=thread_key,
            ref=ref,
            connector=self._connector,
            title=title,
            capabilities=TEAMS_CAPABILITIES,
            interactions=self._interactions,
            files=self._files,
        )


def _type_of(conversation_id: str) -> str:
    """Guess the scope from the id shape.

    Teams does not repeat ``conversationType`` when a conversation is looked up
    rather than delivered, and the surface needs it to know whether it may
    offer a file. A channel or group-chat id carries ``@thread.``; a personal
    chat's does not. Wrong in the safe direction if the shape ever changes: an
    unrecognised id is treated as a channel, which offers no file rather than
    offering one that cannot be accepted.
    """
    return "channel" if "@thread." in conversation_id else "personal"
