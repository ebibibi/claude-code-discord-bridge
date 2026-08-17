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
from collections.abc import Iterable
from dataclasses import dataclass, field

from .mapping import MappingStore
from .rules import AnonymizationRules, Matcher, normalize_category

__all__ = ["Anonymizer", "AnonymizationResult", "Replacement", "is_adoptable"]

# Bounds on what may be adopted from an inspector report. The inspector is a
# local LLM, so its output is untrusted input: a one-character "proper noun"
# would alias a particle and shred every later message, a paragraph reported as
# a name would alias the message itself, and an unbounded list would grow the
# matcher table without limit.
MIN_ADOPT_CHARS = 2
MAX_ADOPT_CHARS = 120
MAX_ADOPT_TERMS = 32


def is_adoptable(value: str) -> bool:
    """Whether ``value`` may be minted from an inspector report.

    The caller needs this too: a term rejected here is still an unreplaced
    proper noun, so it has to keep blocking rather than count as handled.
    """
    return MIN_ADOPT_CHARS <= len(value.strip()) <= MAX_ADOPT_CHARS


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
    _learned: tuple[Matcher, ...] = field(default=(), init=False, repr=False)
    _learned_size: int = field(default=-1, init=False, repr=False)

    # ------------------------------------------------------------ anonymize

    def adopt(self, text: str, terms: Iterable[tuple[str, str]]) -> AnonymizationResult:
        """Mint aliases for ``terms``, then anonymize ``text`` including them.

        Used when the inspector reports a proper noun the rules missed. The
        model decided *what* to hide; this table still decides the alias, so an
        adopted term is exactly as restorable as a rule term — the property the
        whole design rests on. Terms absent from the text are still registered,
        which is what makes the next pass catch them without the model.
        """
        for value, category in list(terms)[:MAX_ADOPT_TERMS]:
            cleaned = (value or "").strip()
            if is_adoptable(cleaned):
                self.store.alias_for(normalize_category(category), cleaned)
        self._invalidate_restore_cache()
        return self.anonymize(text)

    def anonymize(self, text: str) -> AnonymizationResult:
        """Replace every rule hit with its stable alias."""
        if not text:
            return AnonymizationResult(text=text, original_length=len(text or ""))
        if self.rules.is_empty and not self._learned_matchers():
            return AnonymizationResult(text=text, original_length=len(text))

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
        # Rules first: on an equal-length tie the configured category wins over
        # whatever category the inspector guessed when the term was adopted.
        matchers = (*self.rules.matchers, *self._learned_matchers())
        for priority, matcher in enumerate(matchers):
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

    # -------------------------------------------------------------- learned

    def _learned_matchers(self) -> tuple[Matcher, ...]:
        """Literals for every term adopted so far, longest first.

        Rebuilt whenever the store grows. Without this an adopted term would
        depend on the model noticing it again on every later pass; with it,
        one detection is permanent.
        """
        if self._learned_size == len(self.store):
            return self._learned
        pairs = [(c, v) for c, v in self.store.originals() if v]
        # Longest first, for the same reason the rule loader sorts: regex
        # alternation is leftmost-first, not leftmost-longest.
        pairs.sort(key=lambda pair: len(pair[1]), reverse=True)
        self._learned = tuple(
            Matcher(
                pattern=re.compile(re.escape(value), re.IGNORECASE),
                category=category,
                literal=value,
            )
            for category, value in pairs
        )
        self._learned_size = len(self.store)
        return self._learned
