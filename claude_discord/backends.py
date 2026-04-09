"""Backend kinds and shared backend helpers."""

from __future__ import annotations

from typing import Literal, cast

BackendKind = Literal["claude", "codex"]

DEFAULT_BACKEND: BackendKind = "claude"
VALID_BACKENDS: frozenset[str] = frozenset({"claude", "codex"})


def normalize_backend(value: str | None) -> BackendKind:
    """Return a validated backend kind.

    ``None`` maps to the default backend so callers can treat missing backend
    metadata on legacy rows as Claude for backward compatibility.
    """
    if value is None:
        return DEFAULT_BACKEND

    normalized = value.strip().lower()
    if normalized not in VALID_BACKENDS:
        raise ValueError(f"Unsupported backend: {value}")

    return cast(BackendKind, normalized)


def build_resume_command(backend: BackendKind | str | None, session_id: str) -> str:
    """Return the provider-specific CLI resume command."""
    normalized = normalize_backend(backend)
    if normalized == "codex":
        return f"codex exec resume {session_id}"
    return f"claude --resume {session_id}"
