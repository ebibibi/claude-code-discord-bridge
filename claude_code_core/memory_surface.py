"""An in-memory :class:`~claude_code_core.frontend.ConversationSurface`.

Two jobs, both about keeping the protocol honest.

**It proves the contract is satisfiable.** A protocol nobody has implemented is
a wish. This is the smallest thing that passes every check in
:mod:`claude_code_core.conformance`, so a failing check means the surface under
test is wrong — not that the contract is impossible.

**It is the worked example.** Someone writing a Slack surface, or a frontend
for their own deployment, can read one short file that does the whole protocol
rather than reverse-engineer it from the Discord implementation, where the
interesting parts are tangled with discord.py.

It is also genuinely useful in tests: drive a whole session against it and
assert on what the model *said*, with no network and no mocks.

This is a reference implementation, not a toy — where the protocol has a real
obligation (splitting to the message limit, batching files, idempotent
handles), this honours it, because otherwise it would not be proving anything.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from .frontend import (
    ActivitySpec,
    ChoicePrompt,
    FormPrompt,
    Mention,
    Notice,
    OutboundFile,
    StatusKind,
    SurfaceCapabilities,
    ThreadKey,
    derive_thread_key,
)
from .rendering import render_for

__all__ = ["MemoryActivity", "MemorySurface", "MemoryTextStream"]


@dataclass
class MemoryActivity:
    """A started activity, recorded rather than rendered."""

    spec: ActivitySpec
    updates: list[str] = field(default_factory=list)
    result: str | None = None
    ok: bool = True
    finished: bool = False

    async def update(self, detail: str) -> None:
        if self.finished:
            return
        self.updates.append(detail)

    async def complete(self, result: str | None, *, ok: bool = True) -> None:
        if self.finished:
            return  # completing twice is harmless by contract
        self.result = result
        self.ok = ok
        self.finished = True

    async def cancel(self) -> None:
        if self.finished:
            return
        self.finished = True
        self.ok = False


class MemoryTextStream:
    """Accumulates deltas; on finalize, hands the text to the surface."""

    def __init__(self, surface: MemorySurface) -> None:
        self._surface = surface
        self._buffer = ""
        self._finalized = False
        self._result = ""

    @property
    def has_content(self) -> bool:
        return bool(self._buffer)

    async def append(self, delta: str) -> None:
        if self._finalized:
            return
        self._buffer += delta

    async def finalize(self, transform: Callable[[str], str] | None = None) -> str:
        if self._finalized:
            return self._result
        self._finalized = True
        text = transform(self._buffer) if transform and self._buffer else self._buffer
        if text:
            await self._surface.send_text(text)
        self._result = text
        return text


class _MemoryInterrupt:
    def __init__(self, on_stop: Callable[[], Awaitable[None]]) -> None:
        self._on_stop = on_stop
        self.bumps = 0
        self.disabled = False

    async def bump(self) -> None:
        if not self.disabled:
            self.bumps += 1

    async def disable(self) -> None:
        self.disabled = True

    async def fire(self) -> None:
        """Simulate the user pressing Stop."""
        if not self.disabled:
            await self._on_stop()


class MemorySurface:
    """A surface that records instead of sending.

    Args:
        capabilities: The surface being simulated. Pass Teams' or Slack's
            numbers to see how the same session would render there.
        answers: Values ``prompt_choice`` returns, in order. Exhausted or
            empty means "unanswered", which the protocol allows.
        form_answers: Values ``prompt_form`` returns, in order.
    """

    def __init__(
        self,
        capabilities: SurfaceCapabilities | None = None,
        *,
        external_id: str = "memory:1",
        answers: Sequence[Sequence[str]] = (),
        form_answers: Sequence[dict[str, str]] = (),
        working_dir: str | None = None,
    ) -> None:
        self._caps = capabilities or SurfaceCapabilities(max_message_chars=2000)
        self._external_id = external_id
        self._thread_key = derive_thread_key("memory", external_id)
        self.working_dir = working_dir

        self._answers = list(answers)
        self._form_answers = list(form_answers)

        # Recorded output. The ``conformance_*`` names are the hooks the
        # contract checker looks for; the others are for readable assertions.
        self.conformance_sent_text: list[str] = []
        self.conformance_delivered_files: list[str] = []
        self.notices: list[Notice] = []
        self.activities: list[MemoryActivity] = []
        self.statuses: list[StatusKind] = []
        self.prompts: list[ChoicePrompt] = []
        self.forms: list[FormPrompt] = []
        self.urls: list[tuple[str, str]] = []
        self.titles: list[str] = []
        self.interrupts: list[_MemoryInterrupt] = []

    # -- identity ----------------------------------------------------------
    @property
    def thread_key(self) -> ThreadKey:
        return self._thread_key

    @property
    def external_id(self) -> str:
        return self._external_id

    @property
    def frontend(self) -> str:
        return "memory"

    @property
    def capabilities(self) -> SurfaceCapabilities:
        return self._caps

    # -- output ------------------------------------------------------------
    async def send_text(self, text: str) -> str | None:
        parts = render_for(text, self._caps)
        if not parts:
            return None
        self.conformance_sent_text.extend(parts)
        return f"msg-{len(self.conformance_sent_text)}"

    async def send_notice(self, notice: Notice) -> str | None:
        self.notices.append(notice)
        return f"notice-{len(self.notices)}"

    async def deliver_files(self, files: Sequence[OutboundFile]) -> None:
        # Batching is where a real surface loses files: Discord caps a message
        # at 10 attachments, Teams at one consent card. Honour the cap here so
        # the contract check has something real to verify.
        batch = max(self._caps.max_files_per_message, 1)
        for start in range(0, len(files), batch):
            for f in files[start : start + batch]:
                self.conformance_delivered_files.append(f.display_name)

    def open_stream(self) -> MemoryTextStream:
        return MemoryTextStream(self)

    async def open_activity(self, spec: ActivitySpec) -> MemoryActivity:
        activity = MemoryActivity(spec=spec)
        self.activities.append(activity)
        return activity

    # -- state -------------------------------------------------------------
    async def set_status(self, status: StatusKind) -> None:
        self.statuses.append(status)

    async def clear_status(self) -> None:
        pass

    # -- interaction -------------------------------------------------------
    async def prompt_choice(self, prompt: ChoicePrompt) -> tuple[str, ...] | None:
        self.prompts.append(prompt)
        if not self._answers:
            return None
        chosen = tuple(self._answers.pop(0))
        if not prompt.multi_select:
            chosen = chosen[:1]
        return chosen

    async def prompt_form(self, prompt: FormPrompt) -> dict[str, str] | None:
        self.forms.append(prompt)
        if not self._form_answers:
            return None
        return dict(self._form_answers.pop(0))

    async def prompt_url(self, title: str, url: str, *, notify: Mention | None = None) -> bool:
        self.urls.append((title, url))
        return True

    async def offer_interrupt(self, on_stop: Callable[[], Awaitable[None]]) -> _MemoryInterrupt:
        handle = _MemoryInterrupt(on_stop)
        self.interrupts.append(handle)
        return handle

    # -- management --------------------------------------------------------
    async def rename(self, title: str) -> None:
        self.titles.append(title)

    async def recent_transcript(self, days: int) -> str | None:
        return None
