"""The 対応表 (alias mapping table).

This is the single most sensitive file the gateway owns: it is what makes the
replacement reversible, and it is what must never leave the operator's machine.
It is stored as JSON next to the rules file, written atomically.

Determinism contract: for a given store, ``alias_for(category, value)`` returns
the same alias forever. That is what lets an answer be restored, and what lets
two sessions weeks apart talk about the same server.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .rules import Category

logger = logging.getLogger(__name__)

__all__ = ["MappingStore"]

# Alias templates. Values keep the *shape* of what they replace so the external
# model still sees "a hostname" / "an address" and can reason structurally.
_ALIAS_TEMPLATES: dict[str, str] = {
    Category.ORG: "org-{n:03d}",
    Category.PERSON: "person-{n:03d}",
    Category.HOST: "host-{n:03d}",
    Category.DOMAIN: "example-{n:03d}.invalid",
    Category.EMAIL: "person-{n:03d}@example.invalid",
    Category.PROJECT: "project-{n:03d}",
    Category.TERM: "term-{n:03d}",
}
_FALLBACK_TEMPLATE = "{category}-{n:03d}"

# RFC 5737 documentation ranges — safe to hand to an external model, and still
# parseable as an address by whatever it suggests running.
_IPV4_BLOCKS = ("203.0.113.{n}", "198.51.100.{n}", "192.0.2.{n}")
_IPV4_PER_BLOCK = 254


def _alias_for_index(category: str, index: int) -> str:
    """Render the alias for the ``index``-th (1-based) value in ``category``."""
    if category == Category.IPV4:
        block, offset = divmod(index - 1, _IPV4_PER_BLOCK)
        if block < len(_IPV4_BLOCKS):
            return _IPV4_BLOCKS[block].format(n=offset + 1)
        return f"ipv4-{index:03d}"  # ran out of documentation space; stay unique
    template = _ALIAS_TEMPLATES.get(category, _FALLBACK_TEMPLATE)
    return template.format(n=index, category=_safe_category(category))


def _safe_category(category: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in category.lower()).strip("-")
    return cleaned or "term"


@dataclass(frozen=True)
class _Entry:
    alias: str
    original: str
    category: str


class MappingStore:
    """Bidirectional, persistent alias table.

    Not process-safe across multiple bots writing the same file; it is
    thread-safe within one process, which is what ccdb needs (one bot, many
    concurrent sessions).
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        self._by_key: dict[str, _Entry] = {}  # "category\x00casefolded" -> entry
        self._by_alias: dict[str, _Entry] = {}  # casefolded alias -> entry
        self._counters: dict[str, int] = {}
        self._dirty = False
        if self._path is not None:
            self._load()

    # ---------------------------------------------------------------- lookup

    @property
    def path(self) -> Path | None:
        return self._path

    def __len__(self) -> int:
        return len(self._by_alias)

    def alias_for(self, category: str, value: str) -> str:
        """Return the stable alias for ``value``, minting one on first sight."""
        key = f"{category}\x00{value.casefold()}"
        with self._lock:
            existing = self._by_key.get(key)
            if existing is not None:
                return existing.alias
            index = self._counters.get(category, 0) + 1
            alias = _alias_for_index(category, index)
            # Defensive: never hand out an alias that already maps elsewhere.
            while alias.casefold() in self._by_alias:
                index += 1
                alias = _alias_for_index(category, index)
            self._counters[category] = index
            entry = _Entry(alias=alias, original=value, category=category)
            self._by_key[key] = entry
            self._by_alias[alias.casefold()] = entry
            self._dirty = True
            self.flush()
            return alias

    def original_for(self, alias: str) -> str | None:
        """Reverse lookup. Case-insensitive: models rewrite case freely."""
        entry = self._by_alias.get(alias.casefold())
        return entry.original if entry else None

    def aliases(self) -> list[str]:
        with self._lock:
            return [entry.alias for entry in self._by_alias.values()]

    def originals(self) -> list[tuple[str, str]]:
        """Every ``(category, original)`` minted so far.

        This is what lets a term the inspector once flagged be replaced by the
        table on every later pass, without asking the model again.
        """
        with self._lock:
            return [(entry.category, entry.original) for entry in self._by_alias.values()]

    # ----------------------------------------------------------- persistence

    def _load(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt table would silently break restoration, which is worse
            # than refusing to start the feature. Surface it loudly.
            logger.exception("Mapping table %s is unreadable", self._path)
            raise
        for raw in data.get("entries", []):
            entry = _Entry(
                alias=str(raw["alias"]),
                original=str(raw["original"]),
                category=str(raw.get("category", Category.TERM)),
            )
            self._by_key[f"{entry.category}\x00{entry.original.casefold()}"] = entry
            self._by_alias[entry.alias.casefold()] = entry
        for category, count in (data.get("counters") or {}).items():
            self._counters[str(category)] = int(count)

    def flush(self) -> None:
        """Write the table to disk atomically. No-op for in-memory stores."""
        if self._path is None or not self._dirty:
            return
        payload = {
            "version": 1,
            "counters": dict(self._counters),
            "entries": [
                {"alias": e.alias, "original": e.original, "category": e.category}
                for e in self._by_alias.values()
            ],
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)
        try:
            self._path.chmod(0o600)
        except OSError:  # pragma: no cover - platform dependent
            logger.debug("Could not tighten permissions on %s", self._path)
        self._dirty = False
