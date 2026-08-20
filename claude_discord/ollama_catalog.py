"""A curated shortlist of Ollama models worth installing for the local backend.

This is a *suggestion* list, not an allowlist: ``/ollama pull`` accepts any name
Ollama's registry serves. The list exists because the useful question when the
cloud backends are unavailable is not "what exists" (thousands of tags) but
"what will actually drive the Codex CLI on the hardware I have".

Two filters produced it:

* **Tool calling is mandatory.** Codex acts only through tool calls; a model
  without that capability answers in prose where a file edit was required and
  looks broken. Every entry here has it.
* **Size is the real constraint.** Entries are grouped by the memory a run
  needs, because the difference between "fully on the accelerator" and "spilled
  to system RAM" is roughly an order of magnitude in speed.

Deliberately *not* fetched from ollama.com at runtime: the local backend's whole
premise is that a local thread reaches no vendor, and a catalog refresh would be
exactly such a call. The cost is that this list ages — hence
``CATALOG_NOTE``, shown next to the suggestions, pointing at the live registry.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["CatalogEntry", "CATALOG", "CATALOG_NOTE", "catalog_by_name", "fits_in_gb"]

CATALOG_NOTE = (
    "Suggestions only — any tag from ollama.com/library works in `model:`. "
    "All entries below support tool calling, which the Codex CLI requires."
)


@dataclass(frozen=True)
class CatalogEntry:
    """One suggested model, with the number an operator actually needs."""

    name: str
    approx_gb: float
    summary: str
    #: Rough memory a comfortable run needs — weights plus KV cache headroom.
    needs_gb: float

    @property
    def label(self) -> str:
        return f"{self.name} — {self.approx_gb:.0f}GB, {self.summary}"


# Ordered small → large so the autocomplete reads as a ladder: the first entry
# that fits the operator's hardware is the one to try.
CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry(
        "qwen3.5:8b",
        5.2,
        "smallest usable agent; fine for edits, weak at planning",
        needs_gb=8,
    ),
    CatalogEntry(
        "qwen3.5:14b",
        9.0,
        "good quality-per-GB on a single consumer GPU",
        needs_gb=12,
    ),
    CatalogEntry(
        "gemma4:31b",
        20.0,
        "strong general reasoning, long context",
        needs_gb=26,
    ),
    CatalogEntry(
        "glm-4.7-flash",
        19.0,
        "fast MoE, tuned for tool use and code",
        needs_gb=26,
    ),
    CatalogEntry(
        "qwen3.6:35b-a3b",
        22.6,
        "MoE — 35B quality at ~3B speed; also reads images",
        needs_gb=30,
    ),
    CatalogEntry(
        "qwen2.5-coder:32b",
        20.0,
        "code-specialised; best pure editing at this size",
        needs_gb=26,
    ),
    CatalogEntry(
        "gpt-oss:20b",
        14.0,
        "open-weight reasoning model, modest footprint",
        needs_gb=18,
    ),
    CatalogEntry(
        "gpt-oss:120b",
        65.4,
        "open-weight frontier-ish; the usual local default",
        needs_gb=80,
    ),
    CatalogEntry(
        "nemotron-3-super:120b-a12b",
        86.8,
        "largest here; best long-horizon agentic runs",
        needs_gb=100,
    ),
)


def catalog_by_name(name: str) -> CatalogEntry | None:
    """Return the catalog entry whose name matches, ignoring an explicit tag."""
    stem = name.split(":", 1)[0]
    for entry in CATALOG:
        if entry.name == name or entry.name.split(":", 1)[0] == stem:
            return entry
    return None


def fits_in_gb(entry: CatalogEntry, available_gb: float | None) -> bool | None:
    """Whether ``entry`` plausibly fits in ``available_gb``; ``None`` if unknown."""
    if available_gb is None or available_gb <= 0:
        return None
    return entry.needs_gb <= available_gb
