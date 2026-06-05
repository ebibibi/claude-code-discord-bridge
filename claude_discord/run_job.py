"""Engine-neutral one-shot collector for /api/run.

``collect_oneshot`` drives any :class:`SessionBackend`'s ``run(prompt)``
async generator to completion and returns the final text. It works
identically for Claude, Codex, or any future backend because it only
depends on the shared ``StreamEvent`` contract — never on a specific CLI.

Keeping this logic out of the HTTP handler (and out of the backends
themselves) is what lets ``/api/run`` stay engine-agnostic: the endpoint
asks ``create_backend`` for a runner and hands it here; all engine
differences are absorbed behind the ``SessionBackend`` protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from claude_discord.claude.types import MessageType

if TYPE_CHECKING:
    from claude_code_core.backend import SessionBackend


class RunError(Exception):
    """Raised when a backend run yields an error event."""


async def collect_oneshot(backend: SessionBackend, prompt: str) -> str:
    """Run *prompt* on *backend* and return the final assistant text.

    Resolution of the returned text, in priority order:
        1. The RESULT event's ``text`` (or ``raw['result']``) — the
           backend's authoritative final answer.
        2. Otherwise, the concatenation of streamed ASSISTANT text chunks.

    Raises:
        RunError: if any event carries an ``error`` payload.
    """
    assistant_parts: list[str] = []
    result_text: str | None = None

    async for event in backend.run(prompt):
        if event.error:
            raise RunError(event.error)
        if event.message_type == MessageType.ASSISTANT and event.text:
            assistant_parts.append(event.text)
        elif event.message_type == MessageType.RESULT:
            if event.text is not None:
                result_text = event.text
            elif isinstance(event.raw, dict):
                raw_result = event.raw.get("result")
                if isinstance(raw_result, str):
                    result_text = raw_result

    if result_text:
        return result_text
    return "".join(assistant_parts)
