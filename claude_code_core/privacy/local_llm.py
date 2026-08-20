"""Shared transport for the local models that guard the `/ask` hop.

Two callers, one endpoint: the leak inspector asks "does this still name a real
organisation", the answerability judge asks "can this still be answered". The
part worth sharing is not the prompt — it is the pile of gotchas around it:

- ``think: False``, or a thinking model returns an empty ``content`` and every
  caller silently concludes "nothing found";
- ``format: json`` plus a parser that still tolerates fences, because models
  wrap JSON in ``` anyway;
- ``temperature: 0``, because a guard that changes its mind between identical
  runs cannot be reasoned about.

A second hand-rolled copy of this is where those come back one at a time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["chat_json", "extract_json_object", "TRANSPORT_ERRORS"]

# The errors a caller is expected to translate into "unavailable" rather than
# let propagate. Named once so the inspector and the judge agree on the set.
TRANSPORT_ERRORS = (urllib.error.URLError, OSError, TimeoutError)


async def chat_json(
    *,
    base_url: str,
    model: str,
    system: str,
    user: str,
    timeout_seconds: float,
    max_chars: int = 12000,
) -> str:
    """Ask a local Ollama-compatible model one question; return raw content.

    Raises on transport failure — the caller decides what an unreachable model
    means, and the two callers here deliberately decide differently.
    """
    return await asyncio.to_thread(
        _request,
        base_url=base_url.rstrip("/"),
        model=model,
        system=system,
        user=user[:max_chars],
        timeout_seconds=timeout_seconds,
    )


def _request(*, base_url: str, model: str, system: str, user: str, timeout_seconds: float) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": "json",
        # Thinking models return an empty `content` unless this is off.
        "think": False,
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(  # noqa: S310 - operator-configured local URL
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        body = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(body)
    return str(parsed.get("message", {}).get("content", ""))


def extract_json_object(raw: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model reply, or ``None``.

    Tolerates code fences and surrounding prose. Returns ``None`` rather than
    raising: a guard that crashes on a malformed reply is worse than one that
    reports it could not read it.
    """
    text = raw.strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`")
        _, _, text = text.partition("\n")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        logger.debug("Local model reply was not JSON: %.120s", raw)
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        logger.debug("Local model reply was not valid JSON: %.120s", raw)
        return None
    return data if isinstance(data, dict) else None
