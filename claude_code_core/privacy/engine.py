"""Deterministic, reversible replacement engine.

The whole design rests on one property: replacement is a *pure function of the
rules and the mapping table*. Run it a thousand times and ``srv-example-dc01``
becomes the same alias every time — which is the only reason the answer can be
put back together afterwards.

Nothing here calls a model. See ``inspector.py`` for the local-LLM half, whose
job is to *report* leftovers, never to rewrite text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .mapping import MappingStore
from .rules import AnonymizationRules

__all__ = ["Anonymizer", "AnonymizationResult", "Replacement"]


@dataclass(frozen=True)
class Replacement:
    """One original→alias substitution that actually fired."""

    original: str
    alias: str
    category: str
    count: int


@dataclass(frozen=True)
class AnonymizationResult:
    """Outcome of anonymizing one piece of text."""

    text: str
    replacements: tuple[Replacement, ...] = ()
    original_length: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.replacements)

    @property
    def total_substitutions(self) -> int:
        return sum(r.count for r in self.replacements)

    def summary(self) -> str:
        """Human-readable one-liner for logs and audit records."""
        if not self.replacements:
            return "no substitutions"
        parts = [f"{r.original}→{r.alias}(x{r.count})" for r in self.replacements]
        return ", ".join(parts)


@dataclass
class Anonymizer:
    """Applies rules to text and restores aliases in the answer."""

    rules: AnonymizationRules
    store: MappingStore = field(default_factory=MappingStore)
    _restore_pattern: re.Pattern[str] | None = field(default=None, init=False, repr=False)
    _restore_size: int = field(default=-1, init=False, repr=False)

    # ------------------------------------------------------------ anonymize

    def anonymize(self, text: str) -> AnonymizationResult:
        """Replace every rule hit with its stable alias."""
        if not text or self.rules.is_empty:
            return AnonymizationResult(text=text, original_length=len(text or ""))

        spans = self._collect_spans(text)
        if not spans:
            return AnonymizationResult(text=text, original_length=len(text))

        pieces: list[str] = []
        counts: dict[tuple[str, str], int] = {}
        aliases: dict[tuple[str, str], str] = {}
        first_seen: dict[tuple[str, str], str] = {}
        cursor = 0
        for start, end, category in spans:
            original = text[start:end]
            alias = self.store.alias_for(category, original)
            pieces.append(text[cursor:start])
            pieces.append(alias)
            cursor = end
            key = (category, original.casefold())
            counts[key] = counts.get(key, 0) + 1
            aliases.setdefault(key, alias)
            first_seen.setdefault(key, original)
        pieces.append(text[cursor:])

        replacements = tuple(
            Replacement(
                original=first_seen[key],
                alias=aliases[key],
                category=key[0],
                count=count,
            )
            for key, count in counts.items()
        )
        self._invalidate_restore_cache()
        return AnonymizationResult(
            text="".join(pieces),
            replacements=replacements,
            original_length=len(text),
        )

    def _collect_spans(self, text: str) -> list[tuple[int, int, str]]:
        """Find non-overlapping match spans, honouring rule priority.

        Rules earlier in ``rules.matchers`` win ties; literals are already
        sorted longest-first by the loader, so "Contoso Japan" beats "Contoso".
        """
        candidates: list[tuple[int, int, int]] = []  # (start, end, priority)
        categories: dict[tuple[int, int, int], str] = {}
        for priority, matcher in enumerate(self.rules.matchers):
            for match in matcher.pattern.finditer(text):
                start, end = match.span()
                if end <= start:
                    continue
                key = (start, end, priority)
                candidates.append(key)
                categories[key] = matcher.category

        # Longer match first at the same offset, then rule priority.
        candidates.sort(key=lambda c: (c[0], -(c[1] - c[0]), c[2]))

        accepted: list[tuple[int, int, str]] = []
        last_end = 0
        for start, end, priority in candidates:
            if start < last_end:
                continue
            accepted.append((start, end, categories[(start, end, priority)]))
            last_end = end
        return accepted

    # -------------------------------------------------------------- restore

    def restore(self, text: str) -> str:
        """Put the real names back. Case-insensitive: models rewrite case."""
        if not text:
            return text
        pattern = self._get_restore_pattern()
        if pattern is None:
            return text

        def _sub(match: re.Match[str]) -> str:
            original = self.store.original_for(match.group(0))
            return original if original is not None else match.group(0)

        return pattern.sub(_sub, text)

    def _get_restore_pattern(self) -> re.Pattern[str] | None:
        if self._restore_size == len(self.store) and self._restore_pattern is not None:
            return self._restore_pattern
        aliases = self.store.aliases()
        if not aliases:
            self._restore_pattern = None
            self._restore_size = len(self.store)
            return None
        # Longest first: "203.0.113.10" must not be eaten by "203.0.113.1".
        aliases.sort(key=len, reverse=True)
        self._restore_pattern = re.compile("|".join(re.escape(a) for a in aliases), re.IGNORECASE)
        self._restore_size = len(self.store)
        return self._restore_pattern

    def _invalidate_restore_cache(self) -> None:
        self._restore_size = -1
