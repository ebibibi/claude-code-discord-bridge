"""Is the question still a question after anonymization?

Replacement can succeed and still destroy the request. "What are the pros and
cons of org-002?" is perfectly anonymized and perfectly unanswerable: the thing
being asked about *is* the thing that was hidden. The external model then either
guesses or explains that it cannot look up an identifier — a wasted call and a
confusing answer, with the gateway reporting success throughout.

So this module asks one narrow question about the already-anonymized text:
**does answering require knowing what the placeholders stand for?**

Note the failure direction, which is the opposite of ``inspector.py``:

- the inspector guards a *safety* property. Unavailable must mean block, because
  the harm is a real name leaving the machine.
- this judge guards a *quality* property. Unavailable must mean send, because
  the harm is a good question being refused, and the cost of being wrong is one
  wasted call.

Getting that backwards would take `/ask` down entirely whenever the local model
is busy, in the name of saving an API call. ``AnswerabilityVerdict.blocks`` is
the single place the asymmetry lives.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import PrivacyConfig
from .local_llm import TRANSPORT_ERRORS, chat_json, extract_json_object

logger = logging.getLogger(__name__)

__all__ = ["AnswerabilityJudge", "AnswerabilityVerdict", "parse_verdict", "get_judge"]

# Shown to the operator in a chat client, so it is bounded. A model asked for
# one sentence occasionally returns an essay.
MAX_REASON_CHARS = 400

_SYSTEM_PROMPT = (
    "You review a question that is about to be sent to an external AI model.\n"
    "The question has ALREADY been anonymized: real names were replaced with "
    "placeholders such as org-001, person-002, host-003, example-001.invalid, "
    "203.0.113.1. The external model will receive only this text — no files, no "
    "tools, no background on who the placeholders stand for.\n\n"
    "Decide exactly one thing: can the question be answered usefully WITHOUT "
    "knowing the real identity behind the placeholders?\n\n"
    'Answer "answerable": true when the placeholders are incidental — the '
    "question is about a technology, a method, an error, a configuration or a "
    "general situation, and a good answer would be the same whoever org-001 "
    "really is.\n"
    'Answer "answerable": false when the answer REQUIRES the hidden identity — '
    "the question asks about a specific organisation's or person's reputation, "
    "quality, products, prices, history, staff or culture, or compares two "
    "placeholders. No reasoning can recover an identity from a placeholder.\n\n"
    "Judge only that. Do not judge whether the question is well written, "
    "polite, or answerable in principle.\n"
    'Reply with JSON only: {"answerable": true|false, "reason": "<one short '
    'sentence, in the language of the question>"}\n'
    "In the reason, refer to placeholders by their placeholder name. Never "
    "guess or state what a placeholder might really be."
)


@dataclass(frozen=True)
class AnswerabilityVerdict:
    """One judgement about an anonymized question.

    Defaults are deliberately permissive: an unset verdict is a verdict that
    lets the question through.
    """

    answerable: bool = True
    reason: str = ""
    available: bool = True
    error: str | None = None
    model: str = ""

    @property
    def blocks(self) -> bool:
        """Whether this verdict may stop the send.

        Fail *open*: only a judgement that actually ran gets to refuse. An
        unreachable or unreadable judge is not evidence about the question.
        """
        return self.available and not self.answerable


def parse_verdict(raw: str, *, model: str = "") -> AnswerabilityVerdict:
    """Read a model reply into a verdict; anything unreadable fails open."""
    data = extract_json_object(raw)
    if data is None or "answerable" not in data:
        return AnswerabilityVerdict(
            available=False, error="the judge did not return a verdict", model=model
        )
    answerable = bool(data.get("answerable"))
    reason = str(data.get("reason") or "").strip()[:MAX_REASON_CHARS]
    return AnswerabilityVerdict(answerable=answerable, reason=reason, model=model)


class AnswerabilityJudge:
    """Asks a local model whether an anonymized question can still be answered."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen3:4b",
        timeout_seconds: float = 30.0,
        max_chars: int = 12000,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_chars = max_chars

    async def judge(self, text: str) -> AnswerabilityVerdict:
        """Judge ``text``; never raises — failures come back permissive."""
        if not text.strip():
            return AnswerabilityVerdict(model=self.model)
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
            logger.warning("Answerability judge unreachable at %s: %s", self.base_url, exc)
            return AnswerabilityVerdict(available=False, error=str(exc), model=self.model)
        except Exception as exc:  # noqa: BLE001 - a guard must never break the run
            logger.exception("Answerability judge failed")
            return AnswerabilityVerdict(available=False, error=str(exc), model=self.model)

        verdict = parse_verdict(raw, model=self.model)
        if verdict.blocks:
            logger.info("Answerability judge objects: %s", verdict.reason)
        return verdict


def get_judge(config: PrivacyConfig | None = None) -> AnswerabilityJudge | None:
    """Build the judge from the environment, or ``None`` when switched off.

    No separate endpoint to configure: the check rides on the inspector's local
    model, so it works the moment `/ask` works. Returns ``None`` when the
    gateway itself is inactive — with nothing anonymized there is nothing this
    check could object to.
    """
    config = config or PrivacyConfig.from_env()
    if not config.active or not config.answerability_check:
        return None
    return AnswerabilityJudge(
        base_url=config.inspector_url,
        model=config.inspector_model,
        timeout_seconds=config.inspector_timeout,
    )
