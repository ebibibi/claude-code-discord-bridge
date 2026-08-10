"""What crosses the queue between the receiver and the session host.

An envelope is deliberately *not* the raw activity. Two things are added and
one thing is enforced:

**The receiver's verdict travels with the payload.** The session host cannot
re-verify the token — it never sees one — so it has to trust that the receiver
checked. Recording *what* was checked, and when, makes that trust auditable
instead of assumed: a host reading an envelope can see the ``serviceurl`` the
token actually carried rather than the one the body claims.

**The body's serviceUrl is not used for addressing.** The token's claim is,
because that is the field Microsoft signs. This is the same asymmetry the
endpoint enforces inline; moving the endpoint to another machine must not
quietly lose it.

**Size is bounded here, not by the queue.** Azure's queue limit is 64 KB of
base64, and discovering a too-large activity as a queue error means the message
is lost with a stack trace about encoding. Refusing it at the boundary, by
name, is a failure someone can act on.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Envelope", "EnvelopeTooLargeError"]

#: Azure Queue Storage accepts 64 KB per message, and the text is base64 —
#: which costs a third. Leave room for the envelope's own fields.
MAX_ENVELOPE_BYTES = 40 * 1024

ENVELOPE_VERSION = 1


class EnvelopeTooLargeError(Exception):
    """An activity is too big to cross the queue.

    Named rather than generic: the caller has to decide whether to drop it or
    fetch it another way, and "queue write failed" does not tell them which.
    """


@dataclass(frozen=True)
class Envelope:
    """One verified activity, on its way to the session host."""

    activity: dict[str, Any]
    #: The ``serviceurl`` the *token* carried. Addressing uses this, never the
    #: body's copy — the token is the part Microsoft signed.
    service_url: str
    #: When the receiver accepted it, epoch seconds. Lets the host notice a
    #: queue that has fallen behind rather than replaying stale work blindly.
    received_at: float
    #: What the receiver verified. Present so the host can audit the trust it
    #: is extending rather than assume it.
    verified: tuple[str, ...] = field(default=("signature", "issuer", "audience", "expiry"))
    version: int = ENVELOPE_VERSION

    @property
    def activity_id(self) -> str:
        value = self.activity.get("id")
        return value if isinstance(value, str) else ""

    @property
    def activity_type(self) -> str:
        value = self.activity.get("type")
        return value if isinstance(value, str) else ""

    @property
    def conversation_id(self) -> str:
        conversation = self.activity.get("conversation")
        if isinstance(conversation, dict):
            value = conversation.get("id")
            if isinstance(value, str):
                return value
        return ""

    def encode(self) -> str:
        """Serialise for the queue, refusing anything oversized.

        Raises:
            EnvelopeTooLarge: with the measured size, so a log line says how
                far over the limit it was rather than just that it failed.
        """
        raw = json.dumps(self.to_dict(), separators=(",", ":")).encode()
        if len(raw) > MAX_ENVELOPE_BYTES:
            raise EnvelopeTooLargeError(
                f"activity is {len(raw)} bytes, over the {MAX_ENVELOPE_BYTES} byte queue limit"
            )
        return base64.b64encode(raw).decode()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "activity": self.activity,
            "serviceUrl": self.service_url,
            "receivedAt": self.received_at,
            "verified": list(self.verified),
        }

    @classmethod
    def decode(cls, text: str) -> Envelope:
        """Parse a queued message.

        Raises:
            ValueError: for anything this version cannot read. A malformed or
                future-versioned message must not be silently treated as an
                empty activity — that would look like a conversation that said
                nothing.
        """
        try:
            raw = base64.b64decode(text, validate=True)
            payload = json.loads(raw)
        except Exception as exc:  # noqa: BLE001 — any decode failure is one failure
            raise ValueError(f"queued message is not a readable envelope: {exc}") from exc
        return cls.from_dict(payload)

    @classmethod
    def from_dict(cls, payload: Any) -> Envelope:
        if not isinstance(payload, dict):
            raise ValueError("envelope must be a JSON object")
        version = payload.get("version")
        if version != ENVELOPE_VERSION:
            # Refusing a newer version is right: this reader cannot know what
            # a future one means, and guessing would apply half of it.
            raise ValueError(f"unsupported envelope version {version!r}")
        activity = payload.get("activity")
        service_url = payload.get("serviceUrl")
        if not isinstance(activity, dict):
            raise ValueError("envelope has no activity")
        if not isinstance(service_url, str) or not service_url:
            raise ValueError("envelope has no serviceUrl")
        verified = payload.get("verified")
        return cls(
            activity=activity,
            service_url=service_url,
            received_at=float(payload.get("receivedAt") or 0.0),
            verified=tuple(v for v in verified if isinstance(v, str))
            if isinstance(verified, list)
            else (),
        )

    @classmethod
    def wrap(cls, activity: dict[str, Any], service_url: str, *, now: Any = time.time) -> Envelope:
        return cls(activity=activity, service_url=service_url, received_at=now())
