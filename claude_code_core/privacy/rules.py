"""Replacement rule definitions for the anonymization gateway.

Rules are *data*, not code: a JSON file lists the literal terms and regular
expressions that identify the operator's organisation. The engine never asks a
model what to replace — see ``docs/ja/anonymization.md`` for why.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["normalize_category", "Category", "Matcher", "AnonymizationRules", "RulesError"]


class RulesError(ValueError):
    """Raised when a rules file is malformed."""


class Category:
    """Well-known replacement categories.

    Unknown categories are allowed; they fall back to the generic alias
    template. These constants exist so the built-in detectors and the alias
    templates agree on spelling.
    """

    ORG = "org"
    PERSON = "person"
    HOST = "host"
    DOMAIN = "domain"
    EMAIL = "email"
    IPV4 = "ipv4"
    PROJECT = "project"
    TERM = "term"


# An inspector invents its own category names ("organization_name",
# "internal hostname"). Left raw they become the alias, so a hidden name gets
# replaced by something longer than itself in every message. Map them onto the
# categories the alias templates already know.
_CATEGORY_SYNONYMS: dict[str, str] = {
    "org": Category.ORG,
    "organisation": Category.ORG,
    "organization": Category.ORG,
    "company": Category.ORG,
    "corporation": Category.ORG,
    "corp": Category.ORG,
    "employer": Category.ORG,
    "customer": Category.ORG,
    "vendor": Category.ORG,
    "person": Category.PERSON,
    "people": Category.PERSON,
    "human": Category.PERSON,
    "individual": Category.PERSON,
    "employee": Category.PERSON,
    "user": Category.PERSON,
    "username": Category.PERSON,
    "account": Category.PERSON,
    "host": Category.HOST,
    "hostname": Category.HOST,
    "server": Category.HOST,
    "machine": Category.HOST,
    "computer": Category.HOST,
    "device": Category.HOST,
    "domain": Category.DOMAIN,
    "fqdn": Category.DOMAIN,
    "url": Category.DOMAIN,
    "website": Category.DOMAIN,
    "site": Category.DOMAIN,
    "email": Category.EMAIL,
    "mail": Category.EMAIL,
    "ipv4": Category.IPV4,
    "ip": Category.IPV4,
    "address": Category.IPV4,
    "project": Category.PROJECT,
    "product": Category.PROJECT,
    "codename": Category.PROJECT,
    "code": Category.PROJECT,
    "system": Category.PROJECT,
}


def normalize_category(raw: str) -> str:
    """Map a free-form category name onto a known one, or ``term``.

    Word by word, first hit wins: ``organization_name`` is an org because of
    its first word, and the vague ``name`` half is deliberately not a synonym
    of anything. An unrecognised category is not an error — it just falls back
    to the generic alias template.
    """
    cleaned = re.sub(r"[^a-z0-9]+", " ", (raw or "").lower()).strip()
    if not cleaned:
        return Category.TERM
    direct = _CATEGORY_SYNONYMS.get(cleaned.replace(" ", ""))
    if direct is not None:
        return direct
    for word in cleaned.split():
        mapped = _CATEGORY_SYNONYMS.get(word)
        if mapped is not None:
            return mapped
    return Category.TERM


@dataclass(frozen=True)
class Matcher:
    """A compiled rule: what to find, and which category the alias comes from."""

    pattern: re.Pattern[str]
    category: str
    literal: str | None = None  # set for literal terms, None for regex rules


# Built-in detectors. Deliberately conservative: they only fire on shapes that
# are unambiguous. Anything fuzzier belongs in the local-LLM inspector, which
# reports rather than rewrites.
_BUILTIN_PATTERNS: dict[str, str] = {
    Category.EMAIL: r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    Category.IPV4: (
        r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
    ),
}

_DEFAULT_BUILTINS: tuple[str, ...] = (Category.EMAIL, Category.IPV4)


@dataclass(frozen=True)
class AnonymizationRules:
    """An ordered set of matchers plus the categories they draw aliases from."""

    matchers: tuple[Matcher, ...] = ()
    source_path: Path | None = None

    @property
    def is_empty(self) -> bool:
        return not self.matchers

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, source_path: Path | None = None
    ) -> AnonymizationRules:
        """Build rules from a parsed rules document.

        Schema::

            {
              "terms": [{"value": "Contoso", "category": "org"}, "Fabrikam"],
              "patterns": [{"regex": "srv-[a-z0-9]+", "category": "host"}],
              "builtins": ["email", "ipv4"]
            }

        ``terms`` entries may be bare strings (category defaults to ``term``).
        """
        if not isinstance(data, dict):
            raise RulesError("rules document must be a JSON object")

        literals: list[tuple[str, str]] = []
        for raw in data.get("terms", []) or []:
            value, category = _parse_term(raw)
            if value:
                literals.append((value, category))

        # Longest first so "Contoso Japan" wins over "Contoso". Regex alternation
        # is leftmost-*first-alternative*, not leftmost-longest, so the ordering
        # here is what makes nested terms replace correctly.
        literals.sort(key=lambda pair: len(pair[0]), reverse=True)

        matchers: list[Matcher] = [
            Matcher(
                pattern=re.compile(re.escape(value), re.IGNORECASE),
                category=category,
                literal=value,
            )
            for value, category in literals
        ]

        for raw in data.get("patterns", []) or []:
            matchers.append(_parse_pattern(raw))

        builtins = data.get("builtins")
        if builtins is None:
            builtins = list(_DEFAULT_BUILTINS)
        for name in builtins:
            if name not in _BUILTIN_PATTERNS:
                raise RulesError(f"unknown builtin detector: {name!r}")
            matchers.append(Matcher(pattern=re.compile(_BUILTIN_PATTERNS[name]), category=name))

        return cls(matchers=tuple(matchers), source_path=source_path)

    @classmethod
    def load(cls, path: str | Path) -> AnonymizationRules:
        """Load rules from a JSON file. Raises ``RulesError`` on bad input."""
        p = Path(path)
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise RulesError(f"cannot read rules file {p}: {exc}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RulesError(f"invalid JSON in rules file {p}: {exc}") from exc
        return cls.from_dict(data, source_path=p)


def _parse_term(raw: object) -> tuple[str, str]:
    if isinstance(raw, str):
        return raw.strip(), Category.TERM
    if isinstance(raw, dict):
        value = str(raw.get("value", "")).strip()
        category = str(raw.get("category") or Category.TERM).strip() or Category.TERM
        return value, category
    raise RulesError(f"term entry must be a string or object, got {type(raw).__name__}")


def _parse_pattern(raw: object) -> Matcher:
    if not isinstance(raw, dict):
        raise RulesError(f"pattern entry must be an object, got {type(raw).__name__}")
    regex = str(raw.get("regex", "")).strip()
    if not regex:
        raise RulesError("pattern entry is missing 'regex'")
    category = str(raw.get("category") or Category.TERM).strip() or Category.TERM
    flags = re.IGNORECASE if raw.get("ignore_case", True) else 0
    try:
        compiled = re.compile(regex, flags)
    except re.error as exc:
        raise RulesError(f"invalid regex {regex!r}: {exc}") from exc
    if compiled.match(""):
        raise RulesError(f"regex {regex!r} matches the empty string")
    return Matcher(pattern=compiled, category=category)


# Kept module-private but exported for tests and documentation generation.
BUILTIN_PATTERNS: dict[str, str] = dict(_BUILTIN_PATTERNS)
DEFAULT_BUILTINS: tuple[str, ...] = _DEFAULT_BUILTINS
