"""Getting a file out of a session and into Teams.

A bot cannot attach a file to a Teams message the way it can on Discord. What
it can do, in a personal chat, is *offer* one: send a consent card, and if the
user accepts, Teams hands back a one-time upload URL to PUT the bytes to.

That handshake is the reason this module exists as more than a helper. It puts
an attacker-influenced URL in the middle of a path that ends with "write the
contents of a file from this machine to it", so the check that the URL is a
place Microsoft operates is not paranoia — it is the difference between a file
transfer and an exfiltration primitive. The inbound invoke is authenticated, so
this is defence in depth rather than the only control; it is also two lines and
covers the case where something upstream is wrong.

Channels are a different story. Consent cards are personal-scope only, and
posting a file into a channel means writing to its SharePoint folder through
Graph — a different permission, a different API, and a different consent
conversation with the tenant. Until that exists, a channel is told plainly that
the contents were not sent, because a session believing its output was handed
over is worse than one that knows it was not.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any

__all__ = [
    "CONSENT_CARD_CONTENT_TYPE",
    "FILE_INFO_CONTENT_TYPE",
    "FileTransferRegistry",
    "PendingFile",
    "consent_card",
    "file_info_card",
    "is_microsoft_upload_url",
]

logger = logging.getLogger(__name__)

CONSENT_CARD_CONTENT_TYPE = "application/vnd.microsoft.teams.card.file.consent"
FILE_INFO_CONTENT_TYPE = "application/vnd.microsoft.teams.card.file.info"

#: The invoke Teams sends when the user accepts or declines a consent card.
FILE_CONSENT_INVOKE = "fileConsent/invoke"

#: Key ccdb puts in the consent card's context. Namespaced, like the prompt
#: keys, so it cannot collide with anything Teams adds.
FILE_ID_KEY = "ccdb_file"

#: Hosts Microsoft hands out one-time upload URLs on. The bytes of a file from
#: this machine are written to whatever URL the accept invoke names, so the
#: host is checked before anything is sent — an authenticated-but-wrong URL
#: would otherwise be an exfiltration primitive with our own credentials
#: nowhere near it.
ALLOWED_UPLOAD_SUFFIXES = (
    ".sharepoint.com",
    ".sharepoint-df.com",
    ".svc.ms",
    ".onedrive.com",
    ".live.com",
)


@dataclass
class PendingFile:
    """A file offered to a user, waiting for them to accept or decline."""

    id: str
    conversation_id: str
    display_name: str
    content: bytes
    consent_activity_id: str | None = None


class FileTransferRegistry:
    """Files this deployment has offered and not yet finished transferring.

    The same shape as :class:`~claude_teams.interactions.InteractionRegistry`
    and for the same reason: an inbound accept names a transfer, and naming one
    must not be enough to complete it.
    """

    def __init__(self) -> None:
        self._pending: dict[str, PendingFile] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def offer(self, conversation_id: str, display_name: str, content: bytes) -> PendingFile:
        if not conversation_id:
            raise ValueError("conversation_id must not be empty")
        pending = PendingFile(
            id=secrets.token_urlsafe(16),
            conversation_id=conversation_id,
            display_name=display_name,
            content=content,
        )
        self._pending[pending.id] = pending
        return pending

    def claim(self, conversation_id: str, context: Any) -> PendingFile | None:
        """Take the transfer *context* names, if it is really that caller's.

        Returns ``None`` for an unknown id, a conversation that does not match,
        or a transfer already claimed — the same three refusals prompts get,
        for the same reason.
        """
        if not isinstance(context, dict):
            return None
        file_id = context.get(FILE_ID_KEY)
        if not isinstance(file_id, str) or not file_id:
            return None
        pending = self._pending.get(file_id)
        if pending is None:
            return None
        if pending.conversation_id != conversation_id:
            logger.warning("Refused a Teams file accept from another conversation (%s)", file_id)
            return None
        return self._pending.pop(file_id)

    def discard(self, file_id: str) -> None:
        """Forget a transfer — the user declined, or it is finished."""
        self._pending.pop(file_id, None)


def consent_card(pending: PendingFile, *, description: str | None = None) -> dict[str, Any]:
    """The card that asks a user to accept a file.

    ``acceptContext`` and ``declineContext`` come back verbatim on the invoke,
    which is how the answer is tied to the offer without trusting anything else
    in the payload.
    """
    context = {FILE_ID_KEY: pending.id}
    return {
        "contentType": CONSENT_CARD_CONTENT_TYPE,
        "name": pending.display_name,
        "content": {
            "description": description or f"{pending.display_name} from your session",
            "sizeInBytes": len(pending.content),
            "acceptContext": context,
            "declineContext": context,
        },
    }


def file_info_card(name: str, upload_info: dict[str, Any]) -> dict[str, Any]:
    """The card shown once the bytes are in place, linking to the file."""
    return {
        "contentType": FILE_INFO_CONTENT_TYPE,
        "contentUrl": upload_info.get("contentUrl"),
        "name": name,
        "content": {
            "uniqueId": upload_info.get("uniqueId"),
            "fileType": upload_info.get("fileType"),
        },
    }


def is_microsoft_upload_url(url: Any) -> bool:
    """Whether *url* is somewhere Microsoft hands out upload sessions.

    Checked on the **host**, not with a substring: ``https://evil.example.com/
    ?x=.sharepoint.com`` contains the suffix and is not SharePoint. A weak
    check here is the whole vulnerability rather than a smaller version of it.
    """
    if not isinstance(url, str) or not url:
        return False
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(
        host == suffix.lstrip(".") or host.endswith(suffix) for suffix in ALLOWED_UPLOAD_SUFFIXES
    )
