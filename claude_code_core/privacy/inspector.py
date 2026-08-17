"""Local-LLM leftover inspector.

The model here has exactly one job: look at *already anonymized* text and point
at proper nouns the rules did not cover. It never rewrites anything — if it
did, the substitution would stop being deterministic and the answer could no
longer be restored.

Transport is plain ``urllib`` against an Ollama-compatible endpoint, run in a
worker thread (see ``local_llm.py``). No new dependency, and no network call
that isn't the local one the operator configured.

Contrast with ``answerability.py``, which shares the transport and reverses the
failure direction: an unreachable inspector must block, because the harm it
guards against is a real name leaving the machine.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .local_llm import TRANSPORT_ERRORS, chat_json, extract_json_object

logger = logging.getLogger(__name__)

__all__ = ["LocalLlmInspector", "InspectionResult", "Suspect"]

_SYSTEM_PROMPT = (
    "You are a privacy leak detector. You are given text that has ALREADY been "
    "anonymized by a rule-based system. Your only job is to list identifiers "
    "that still look like they belong to a REAL organization: company names, "
    "person names, internal hostnames, domain names, project code names, "
    "account names, license keys.\n"
    "Placeholder tokens such as org-001, person-002, host-003, "
    "example-001.invalid, 203.0.113.x are the anonymizer's own output — never "
    "report those.\n"
    "Generic technology names (Windows, Azure, Python, Kubernetes, GitHub) are "
    "NOT identifiers — never report those.\n"
    'Reply with JSON only: {"suspects": [{"value": "...", "kind": "...", '
    '"reason": "..."}]}. Empty list if the text is clean.'
)


@dataclass(frozen=True)
class Suspect:
    """A term the local model thinks still identifies someone."""

    value: str
    kind: str = ""
    reason: str = ""


@dataclass(frozen=True)
class InspectionResult:
    """Outcome of one inspection pass."""

    suspects: tuple[Suspect, ...] = ()
    available: bool = True
    error: str | None = None
    model: str = ""

    @property
    def clean(self) -> bool:
        """True only when the inspector ran *and* found nothing."""
        return self.available and not self.suspects

    def summary(self) -> str:
        if not self.available:
            return f"inspector unavailable: {self.error}"
        if not self.suspects:
            return "clean"
        return ", ".join(f"{s.value} ({s.kind})" for s in self.suspects)


class LocalLlmInspector:
    """Calls a local Ollama-compatible model to find replacement misses."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3:4b",
        timeout_seconds: float = 30.0,
        max_chars: int = 12000,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_chars = max_chars

    async def inspect(self, text: str) -> InspectionResult:
        """Inspect ``text``; never raises — failures come back as ``available=False``."""
        if not text.strip():
            return InspectionResult(model=self.model)
        try:
            raw = await chat_json(
                base_url=self.base_url,
                model=self.model,
                system=_SYSTEM_PROMPT,
                user=text,
                timeout_seconds=self.timeout_seconds,
                max_chars=self.max_chars,
            )
        except TRANSPORT_ERRORS as exc:
            logger.warning("Local inspector unreachable at %s: %s", self.base_url, exc)
            return InspectionResult(available=False, error=str(exc), model=self.model)
        except Exception as exc:  # noqa: BLE001 - inspector must never break a run
            logger.exception("Local inspector failed")
            return InspectionResult(available=False, error=str(exc), model=self.model)

        suspects = _parse_suspects(raw)
        # Hallucination guard: a suspect that does not literally occur in the
        # text is the model inventing work for a human. Drop it.
        present = tuple(s for s in suspects if s.value and s.value in text)
        dropped = len(suspects) - len(present)
        if dropped:
            logger.info("Inspector proposed %d suspect(s) absent from the text", dropped)
        return InspectionResult(suspects=present, model=self.model)


def _parse_suspects(raw: str) -> tuple[Suspect, ...]:
    """Parse the model's JSON reply, tolerating fenced or padded output."""
    data = extract_json_object(raw)
    if data is None:
        return ()
    entries = data.get("suspects")
    if not isinstance(entries, list):
        return ()
    suspects: list[Suspect] = []
    for entry in entries:
        if isinstance(entry, str):
            suspects.append(Suspect(value=entry.strip()))
        elif isinstance(entry, dict):
            suspects.append(
                Suspect(
                    value=str(entry.get("value", "")).strip(),
                    kind=str(entry.get("kind", "")).strip(),
                    reason=str(entry.get("reason", "")).strip(),
                )
            )
    return tuple(s for s in suspects if s.value)
