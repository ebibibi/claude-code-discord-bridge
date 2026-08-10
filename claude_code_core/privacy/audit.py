"""Append-only audit trail for everything that crossed the boundary.

"いつ・誰が・何を送ったか" — without this the gateway would just be a filter,
and the operator would still be unable to answer an auditor's question.

What is recorded: the anonymized text (what actually left the machine), the
aliases used, the inspector verdict, and the decision. What is NOT recorded:
the original text. The originals live only in the mapping table.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["AuditLog"]


class AuditLog:
    """JSON Lines writer. Never raises into the request path."""

    def __init__(self, path: str | Path | None, *, include_text: bool = True) -> None:
        self._path = Path(path) if path is not None else None
        self._include_text = include_text
        self._lock = threading.Lock()

    @property
    def path(self) -> Path | None:
        return self._path

    def record(self, event: str, **fields: Any) -> None:
        """Append one record. Disabled (path=None) means silently skip."""
        if self._path is None:
            return
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "event": event,
        }
        if not self._include_text:
            fields.pop("text", None)
        payload.update({k: v for k, v in fields.items() if v is not None})
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                existed = self._path.exists()
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line)
                if not existed:
                    os.chmod(self._path, 0o600)
        except OSError:
            # An unwritable audit log is a real problem, but failing the user's
            # message over it would be worse. Log loudly instead of silently.
            logger.exception("Failed to append to audit log %s", self._path)
