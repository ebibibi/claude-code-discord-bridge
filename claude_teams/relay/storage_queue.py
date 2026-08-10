"""Azure Queue Storage over its REST API, with no SDK.

The project's own guidance rules out heavy dependencies most users will never
need, and the Azure SDK is a large tree to pull in for four HTTP calls. The
REST surface here is small: put, get, delete, and a `visibilitytimeout` that
does the lease.

Two details are not obvious and cost an evening if you get them wrong.

**Messages are XML, even though everything else is JSON.** A put wraps the text
in ``<QueueMessage><MessageText>…</MessageText></QueueMessage>`` and a get
returns a list in the same shape. The payload we carry is base64 already, so
nothing needs escaping — but the wrapper is still XML and a JSON body is
silently rejected.

**A SAS token is a credential in a URL.** It never goes in a log line, an
exception message, or a repr. The failure messages here name the operation and
the status code and nothing else, which is the same rule the outbound token
provider follows for the same reason.

The XML is parsed with :mod:`defusedxml`, not the standard library. The
document comes from Azure, which is not the point: it arrives over a network as
bytes this process did not write, and stdlib parsers expand entities by
default. "The source is trusted" is an assumption about the network, and this
is one line either way.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

from .queue import QueuedItem

logger = logging.getLogger(__name__)

__all__ = ["StorageQueue"]

#: How long a pulled message stays invisible while the host works on it. Long
#: enough for a session to start and the handler to return; short enough that a
#: crash does not strand the message for an hour.
DEFAULT_LEASE_SECONDS = 120

#: Queue Storage caps a single get at 32 messages.
MAX_BATCH = 32


class StorageQueue:
    """One Azure Storage queue, addressed by a SAS URL.

    Args:
        queue_url: ``https://<account>.queue.core.windows.net/<queue>?<sas>``.
            The SAS is the credential; treat the whole string as a secret.
        request: ``async (method, url, *, data, headers) -> (status, text)``.
            Injected like every other transport in this package, so the
            behaviour here is testable without a storage account.
    """

    def __init__(
        self,
        queue_url: str,
        request: Any,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        parts = urlsplit(queue_url)
        if parts.scheme != "https" or not parts.netloc:
            raise ValueError("queue_url must be an https URL")
        self._base = f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/")
        self._sas = parts.query
        if not self._sas:
            raise ValueError("queue_url must carry a SAS token")
        self._request = request
        self._lease = lease_seconds

    # -- ActivityQueue -----------------------------------------------------

    async def push(self, text: str) -> None:
        body = f"<QueueMessage><MessageText>{text}</MessageText></QueueMessage>"
        status, _ = await self._call(
            "POST", f"{self._base}/messages?{self._sas}", data=body.encode()
        )
        if status >= 400:
            raise RuntimeError(f"queue put failed with {status}")

    async def pull(self, *, max_items: int = 8, wait_seconds: float = 20.0) -> list[QueuedItem]:
        """Take up to *max_items*.

        Queue Storage has no long poll, so *wait_seconds* is accepted and
        ignored: the puller's idle pause is what keeps this from spinning.
        Silently accepting a parameter it cannot honour is better than a
        signature that does not match the protocol, and worse than saying so —
        hence this paragraph.
        """
        count = max(1, min(max_items, MAX_BATCH))
        url = (
            f"{self._base}/messages?numofmessages={count}"
            f"&visibilitytimeout={self._lease}&{self._sas}"
        )
        status, text = await self._call("GET", url)
        if status >= 400:
            raise RuntimeError(f"queue get failed with {status}")
        return _parse_messages(text)

    async def ack(self, item: QueuedItem) -> None:
        receipt = item.receipt
        if not isinstance(receipt, tuple) or len(receipt) != 2:
            raise ValueError("this item did not come from a StorageQueue")
        message_id, pop_receipt = receipt
        from urllib.parse import quote

        # safe="" matters: the default leaves "/" alone, and pop receipts
        # routinely contain one. Half-encoded, the delete targets a different
        # receipt, silently fails, and the message comes back forever.
        url = (
            f"{self._base}/messages/{message_id}"
            f"?popreceipt={quote(pop_receipt, safe='')}&{self._sas}"
        )
        status, _ = await self._call("DELETE", url)
        if status >= 400 and status != 404:
            # 404 means it is already gone, which is the state we wanted.
            raise RuntimeError(f"queue delete failed with {status}")

    async def _call(self, method: str, url: str, *, data: bytes | None = None) -> tuple[int, str]:
        headers = {"x-ms-version": "2021-08-06"}
        if data is not None:
            headers["Content-Type"] = "application/xml"
        return await self._request(method, url, data=data, headers=headers)


def _parse_messages(text: str) -> list[QueuedItem]:
    """Turn a ``QueueMessagesList`` document into items.

    A message missing its id or pop receipt is skipped rather than returned:
    without both it can never be deleted, so handing it to the puller would
    guarantee an infinite redelivery of something nothing can acknowledge.
    """
    if not text.strip():
        return []
    from defusedxml import ElementTree as DefusedET

    try:
        root = DefusedET.fromstring(text)
    except Exception as exc:  # noqa: BLE001 — any parse failure is one failure
        raise RuntimeError(f"queue returned an unparseable document: {exc}") from exc

    items: list[QueuedItem] = []
    for node in root.findall("QueueMessage"):
        message_id = node.findtext("MessageId")
        pop_receipt = node.findtext("PopReceipt")
        body = node.findtext("MessageText") or ""
        if not message_id or not pop_receipt:
            logger.warning("Skipping a queue message with no id or pop receipt")
            continue
        dequeue_count = node.findtext("DequeueCount") or ""
        items.append(
            QueuedItem(
                text=body,
                receipt=(message_id, pop_receipt),
                delivery_count=int(dequeue_count) if dequeue_count.isdigit() else 1,
            )
        )
    return items


def aiohttp_request(session: Any) -> Any:
    """Adapt an ``aiohttp.ClientSession`` to the request callable above."""

    async def call(
        method: str, url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None
    ) -> tuple[int, str]:
        async with session.request(method, url, data=data, headers=headers) as response:
            return response.status, await response.text()

    return call
