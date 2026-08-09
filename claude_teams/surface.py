"""``TeamsSurface`` — one Teams conversation, speaking the shared vocabulary.

This is where the abstraction earns its keep or does not. The protocol names
intents; this file decides what each intent *is* in Teams, and the answers are
mostly not what Discord does:

============================  ==========================  =====================
Intent                        Discord                     Teams (here)
============================  ==========================  =====================
a long answer                 fifteen messages            one message
``open_activity``             an embed per tool           a line on one card
``set_status``                emoji on the user's         the status row of
                              message                     that same card
``deliver_files``             inline attachment           **not yet** — see
                                                          below
============================  ==========================  =====================

The card is the centrepiece. A tool starting, the status changing and a tool
finishing are three events and one operation — repaint — so inside a single
pacing interval they cost one slot rather than three. Given 1,800 operations
per hour per conversation, that difference is the difference between a session
that keeps showing its work for an hour and one that goes quiet halfway
through.

What this surface deliberately does not claim
---------------------------------------------
``deliver_files`` names the files and says plainly that their contents have not
been transferred. A bot cannot attach a file to a Teams channel message; real
delivery is an upload plus a consent card, and it needs an interaction this
surface cannot yet route. Rather than let the conformance run report a green it
has not earned, the gap is pinned by name in
``tests/test_teams_conformance.py``.

``prompt_choice`` and ``prompt_form`` post the question so a human can see it
and then return ``None`` — "unanswered", which the contract allows and which
callers already handle by applying their own default. That is honest: the
Adaptive Card actions that make them answerable arrive with the invoke handler
that can receive the reply.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from claude_code_core.frontend import (
    ActivitySpec,
    ChoicePrompt,
    FormPrompt,
    Mention,
    Notice,
    NoticeLevel,
    OutboundFile,
    StatusKind,
    SurfaceCapabilities,
    ThreadKey,
)
from claude_code_core.rendering import render_for

from .capabilities import TEAMS_CAPABILITIES
from .cards import ActivityLine, SessionCard
from .conversation import ConversationRef
from .pacer import UpdatePacer

__all__ = ["TEAMS_FRONTEND", "TeamsSurface"]

logger = logging.getLogger(__name__)

TEAMS_FRONTEND = "teams"

#: Pacer keys. The card and a streaming reply are different messages, so they
#: coalesce separately — otherwise a repaint would swallow a pending edit and
#: the answer would stop growing for no visible reason.
_CARD_KEY = "card"
_STREAM_KEY = "stream"

_NOTICE_PREFIX: dict[NoticeLevel, str] = {
    NoticeLevel.INFO: "ℹ️",
    NoticeLevel.SUCCESS: "✅",
    NoticeLevel.WARNING: "⚠️",
    NoticeLevel.ERROR: "❌",
    NoticeLevel.SUBTLE: "",
}


class TeamsSurface:
    """A single Teams conversation, driven through the shared protocol."""

    def __init__(
        self,
        *,
        thread_key: ThreadKey,
        ref: ConversationRef,
        connector: Any,
        title: str = "Session",
        capabilities: SurfaceCapabilities = TEAMS_CAPABILITIES,
        pacer: UpdatePacer | None = None,
    ) -> None:
        """
        Args:
            ref: Where this conversation lives. Replies are posted fresh
                rather than threaded under one message, because a session's
                output is a conversation of its own.
            connector: Something with ``send_activity`` and ``update_activity``.
            pacer: Defaults to one built from the capabilities' resolved
                interval — the number that already accounts for the hourly
                quota.
        """
        self._thread_key = thread_key
        self._ref = ref
        self._connector = connector
        self._capabilities = capabilities
        self._pacer = pacer or UpdatePacer(capabilities.min_update_interval)

        self._card_title = title
        self._status: StatusKind | None = None
        self._activities: list[ActivityLine] = []
        self._card_id: str | None = None

    # -- identity ----------------------------------------------------------

    @property
    def thread_key(self) -> ThreadKey:
        return self._thread_key

    @property
    def external_id(self) -> str:
        return self._ref.conversation_id

    @property
    def frontend(self) -> str:
        return TEAMS_FRONTEND

    @property
    def capabilities(self) -> SurfaceCapabilities:
        return self._capabilities

    @property
    def ref(self) -> ConversationRef:
        return self._ref

    # -- output ------------------------------------------------------------

    async def send_text(self, text: str) -> str | None:
        """Post assistant text, split only if it genuinely does not fit.

        At 80,000 characters per message that is rare, which is the visible
        payoff of driving the chunker from capabilities: the answer Discord
        fragments into fifteen messages arrives here as one.
        """
        last: str | None = None
        for chunk in render_for(text, self._capabilities):
            if chunk.strip():
                last = await self._post({"type": "message", "text": chunk})
        return last

    async def send_notice(self, notice: Notice) -> str | None:
        rendered = _render_notice(notice)
        if not rendered:
            return None
        return await self._post({"type": "message", "text": rendered})

    async def deliver_files(self, files: Sequence[OutboundFile]) -> None:
        """Name the files, and say that their contents have not been sent.

        A bot cannot attach a file to a Teams channel message. Real delivery
        is an upload plus a consent card the user accepts, which needs an
        interaction this surface cannot route yet. Saying so is the point: a
        silent no-op would leave a session believing its output was handed
        over.
        """
        if not files:
            return
        names = "\n".join(f"- {f.display_name}" for f in files)
        await self._post(
            {
                "type": "message",
                "text": (
                    f"**{len(files)} file(s) produced.** File transfer is not available in "
                    f"this Teams build yet, so the contents have **not** been sent:\n{names}"
                ),
            }
        )

    def open_stream(self) -> TeamsTextStream:
        return TeamsTextStream(self)

    async def open_activity(self, spec: ActivitySpec) -> TeamsActivity:
        index = len(self._activities)
        self._activities.append(ActivityLine(title=spec.title, state="running", detail=spec.detail))
        await self._repaint()
        return TeamsActivity(self, index)

    # -- state -------------------------------------------------------------

    async def set_status(self, status: StatusKind) -> None:
        if status == self._status:
            return
        self._status = status
        await self._repaint()

    async def clear_status(self) -> None:
        if self._status is None:
            return
        self._status = None
        await self._repaint()

    # -- interaction -------------------------------------------------------

    async def prompt_choice(self, prompt: ChoicePrompt) -> tuple[str, ...] | None:
        """Show the question; return ``None`` because nothing can answer yet.

        ``None`` means unanswered, and callers already know what to do with
        it — a permission request applies its ``default_on_timeout``, which
        denies. Returning a *choice* here instead would be the dangerous
        failure: the caller cannot tell "the user allowed it" from "the
        surface invented allow".
        """
        lines = [f"**{prompt.header}**" if prompt.header else "", prompt.question]
        lines.extend(f"- `{c.value}` — {c.label}" for c in prompt.choices)
        lines.append("_Answering from Teams is not wired up yet._")
        await self._post({"type": "message", "text": "\n".join(x for x in lines if x)})
        return None

    async def prompt_form(self, prompt: FormPrompt) -> dict[str, str] | None:
        lines = [f"**{prompt.title}**"]
        if prompt.description:
            lines.append(prompt.description)
        lines.extend(f"- {f.label}" for f in prompt.fields)
        lines.append("_Answering from Teams is not wired up yet._")
        await self._post({"type": "message", "text": "\n".join(lines)})
        return None

    async def prompt_url(self, title: str, url: str, *, notify: Mention | None = None) -> bool:
        await self._post({"type": "message", "text": f"**{title}**\n{url}"})
        return False

    async def offer_interrupt(self, on_stop: Callable[[], Awaitable[None]]) -> TeamsInterruptHandle:
        """Hand back an inert handle until an action can be routed to it.

        No Stop control is rendered. An ``Action.Execute`` that nothing answers
        shows the user an error when they press it, which is worse than the
        absence of a button.
        """
        return TeamsInterruptHandle(on_stop)

    # -- management --------------------------------------------------------

    async def rename(self, title: str) -> None:
        """Retitle the card. Teams reply chains have no name of their own."""
        if not title or title == self._card_title:
            return
        self._card_title = title
        await self._repaint()

    async def recent_transcript(self, days: int) -> str | None:
        """Not available: reading conversation history needs Graph, not the
        Bot Connector. ``None`` is the contract's "no transcript"."""
        return None

    async def close(self) -> None:
        """Flush the last state and stop pacing."""
        await self._pacer.flush()
        await self._pacer.close()

    # -- internals ---------------------------------------------------------

    async def _post(self, body: dict[str, Any]) -> str | None:
        return await self._connector.send_activity(self._ref.without_reply(), body)

    async def _repaint(self) -> None:
        """Queue a card repaint.

        The closure reads the surface's state when it *runs*, not when it is
        submitted. That is what makes coalescing correct: three changes inside
        one interval collapse into one paint of the state as it is by then,
        rather than one paint of whichever change happened to win.
        """
        await self._pacer.submit(self._paint_card, key=_CARD_KEY)

    async def _paint_card(self) -> None:
        card = SessionCard(
            title=self._card_title,
            status=self._status,
            activities=tuple(self._activities),
        )
        body = {"type": "message", "attachments": [card.to_attachment()]}
        if self._card_id is None:
            self._card_id = await self._connector.send_activity(self._ref.without_reply(), body)
        else:
            await self._connector.update_activity(self._ref, self._card_id, body)

    async def _replace_activity(self, index: int, line: ActivityLine) -> None:
        if 0 <= index < len(self._activities):
            self._activities[index] = line
            await self._repaint()


class TeamsActivity:
    """One unit of work, shown as a line on the session card."""

    def __init__(self, surface: TeamsSurface, index: int) -> None:
        self._surface = surface
        self._index = index
        self._finished = False

    def _line(self) -> ActivityLine:
        return self._surface._activities[self._index]

    async def update(self, detail: str) -> None:
        if self._finished:
            return
        line = self._line()
        await self._surface._replace_activity(
            self._index, ActivityLine(title=line.title, state="running", detail=detail)
        )

    async def complete(self, result: str | None, *, ok: bool = True) -> None:
        """Finish the line. Completing twice is harmless — a session that
        errors after finishing a tool must not take the surface down too."""
        if self._finished:
            return
        self._finished = True
        line = self._line()
        await self._surface._replace_activity(
            self._index,
            ActivityLine(
                title=line.title,
                state="done" if ok else "failed",
                detail=line.detail,
                result=result,
            ),
        )

    async def cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        line = self._line()
        await self._surface._replace_activity(
            self._index, ActivityLine(title=line.title, state="cancelled", detail=line.detail)
        )


class TeamsTextStream:
    """An answer revealed by editing the message it is being written into.

    Discord streams by editing one message and starting another when it fills
    up at 2,000 characters. Here the message holds 80,000, so the overflow path
    is rare — but it still exists, and the state that makes it correct is
    ``_shown``: what each already-posted message currently displays. Only the
    ones whose text actually changed are re-sent, so a stream crossing a
    boundary does not repaint everything above it.
    """

    def __init__(self, surface: TeamsSurface) -> None:
        self._surface = surface
        self._text = ""
        self._ids: list[str | None] = []
        self._shown: list[str] = []
        self._final: str | None = None

    @property
    def has_content(self) -> bool:
        return bool(self._text)

    async def append(self, delta: str) -> None:
        if not delta or self._final is not None:
            return
        self._text += delta
        await self._surface._pacer.submit(self._paint, key=_STREAM_KEY)

    async def finalize(self, transform: Callable[[str], str] | None = None) -> str:
        """Flush and stop. Returns the text that was shown.

        Idempotent: the session-end path and an error path can both reach it,
        and a second call must not repost the answer.
        """
        if self._final is not None:
            return self._final
        if transform is not None:
            self._text = transform(self._text)
        self._final = self._text
        await self._surface._pacer.flush()
        await self._paint()
        return self._final

    async def _paint(self) -> None:
        if not self._text.strip():
            return
        chunks = render_for(self._text, self._surface.capabilities)
        for index, chunk in enumerate(chunks):
            if index >= len(self._ids):
                activity_id = await self._surface._post({"type": "message", "text": chunk})
                self._ids.append(activity_id)
                self._shown.append(chunk)
                continue
            if self._shown[index] == chunk:
                continue
            self._shown[index] = chunk
            activity_id = self._ids[index]
            if activity_id is None:
                # The service accepted the message without naming it, so there
                # is nothing to edit. Losing the tail is worse than a duplicate.
                self._ids[index] = await self._surface._post({"type": "message", "text": chunk})
                continue
            await self._surface._connector.update_activity(
                self._surface.ref, activity_id, {"type": "message", "text": chunk}
            )


class TeamsInterruptHandle:
    """The Stop control's placeholder until an action can be routed to it."""

    def __init__(self, on_stop: Callable[[], Awaitable[None]]) -> None:
        self._on_stop = on_stop
        self._disabled = False

    async def bump(self) -> None:
        """No-op: the card stays in place, so there is nothing to move."""

    async def disable(self) -> None:
        self._disabled = True

    async def fire(self) -> None:
        """Run the stop callback. The seam the invoke handler will use."""
        if not self._disabled:
            await self._on_stop()


def _render_notice(notice: Notice) -> str:
    prefix = _NOTICE_PREFIX.get(notice.level, "")
    lines: list[str] = []
    if notice.title:
        lines.append(f"{prefix} **{notice.title}**".strip())
    if notice.body:
        lines.append(f"```\n{notice.body}\n```" if notice.monospace_body else notice.body)
    lines.extend(f"**{name}**: {value}" for name, value in notice.fields)
    return "\n".join(lines)
