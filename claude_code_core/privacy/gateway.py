"""The gateway: rules → replacement → local inspection → decision → audit.

One object owns the whole boundary crossing, so the policy lives in exactly one
place and can be tested without a Discord bot or a CLI subprocess.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from .audit import AuditLog
from .config import InspectionPolicy, PrivacyConfig
from .engine import AnonymizationResult, Anonymizer
from .inspector import InspectionResult, LocalLlmInspector
from .mapping import MappingStore
from .rules import AnonymizationRules

logger = logging.getLogger(__name__)

__all__ = ["PrivacyGateway", "GuardOutcome", "get_gateway", "reset_gateway_cache"]


@dataclass(frozen=True)
class GuardOutcome:
    """Whether the text may leave, and in what form."""

    allowed: bool
    text: str
    result: AnonymizationResult
    inspection: InspectionResult | None = None
    reason: str | None = None
    warning: str | None = None


@dataclass
class PrivacyGateway:
    """Anonymize outbound text, inspect it locally, restore inbound text."""

    anonymizer: Anonymizer
    inspector: LocalLlmInspector | None = None
    policy: str = InspectionPolicy.BLOCK
    audit: AuditLog = field(default_factory=lambda: AuditLog(None))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    async def guard(self, text: str, **context: Any) -> GuardOutcome:
        """Anonymize ``text`` and decide whether it may be sent."""
        with self._lock:
            result = self.anonymizer.anonymize(text)

        inspection: InspectionResult | None = None
        if self.policy != InspectionPolicy.OFF and self.inspector is not None:
            inspection = self._drop_own_output(await self.inspector.inspect(result.text))

        allowed, reason, warning = self._decide(inspection)
        self.audit.record(
            "outbound",
            allowed=allowed,
            reason=reason,
            warning=warning,
            policy=self.policy,
            substitutions=[
                {"alias": r.alias, "category": r.category, "count": r.count}
                for r in result.replacements
            ],
            inspector=(inspection.summary() if inspection else "not run"),
            text=result.text,
            **context,
        )
        if not allowed:
            logger.warning("Anonymization gateway blocked a message: %s", reason)
        elif warning:
            logger.warning("Anonymization gateway warning: %s", warning)

        return GuardOutcome(
            allowed=allowed,
            text=result.text,
            result=result,
            inspection=inspection,
            reason=reason,
            warning=warning,
        )

    def _drop_own_output(self, inspection: InspectionResult) -> InspectionResult:
        """Discard suspects that are the anonymizer's own placeholders.

        Observed in practice: told in plain language to ignore placeholders, a
        local model still reports ``person-001@example.invalid`` as a real
        address — and under the block policy that false positive stops a
        message that was already safe. Asking the model more nicely is not a
        fix; checking against the mapping table is. If restoring a suspect
        changes it, we minted it, so it cannot be a leak.
        """
        if not inspection.suspects:
            return inspection
        with self._lock:
            kept = tuple(
                s for s in inspection.suspects if self.anonymizer.restore(s.value) == s.value
            )
        dropped = len(inspection.suspects) - len(kept)
        if dropped:
            logger.debug("Dropped %d inspector suspect(s) that were our own aliases", dropped)
        if dropped == 0:
            return inspection
        return dataclasses.replace(inspection, suspects=kept)

    def _decide(self, inspection: InspectionResult | None) -> tuple[bool, str | None, str | None]:
        if inspection is None:
            return True, None, None

        if not inspection.available:
            detail = (
                f"the local inspector ({inspection.model}) could not be reached: {inspection.error}"
            )
            if self.policy == InspectionPolicy.BLOCK:
                return (
                    False,
                    (
                        f"Blocked before sending: {detail}. Nothing was sent to the "
                        "external model. Start the local model, or set "
                        "CCDB_ANONYMIZE_POLICY=warn to send without inspection."
                    ),
                    None,
                )
            return True, None, f"Sent without inspection — {detail}"

        if not inspection.suspects:
            return True, None, None

        listed = ", ".join(f"`{s.value}`" for s in inspection.suspects)
        if self.policy == InspectionPolicy.BLOCK:
            return (
                False,
                (
                    "Blocked before sending: the local inspector still sees "
                    f"identifying terms — {listed}. Nothing was sent to the external "
                    "model. Add them to the replacement rules, or rephrase."
                ),
                None,
            )
        return True, None, f"Possible replacement misses sent anyway: {listed}"

    def restore(self, text: str) -> str:
        """Turn aliases back into the real names for display."""
        with self._lock:
            return self.anonymizer.restore(text)


# --------------------------------------------------------------------------
# Process-wide accessor. Rules are re-read when the file changes on disk, so
# adding a term does not require restarting the bot.
# --------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cached_gateway: PrivacyGateway | None = None
_cached_signature: tuple[Any, ...] | None = None


def _signature(config: PrivacyConfig) -> tuple[Any, ...]:
    try:
        mtime = config.rules_path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    return (
        str(config.rules_path),
        mtime,
        str(config.mapping_path),
        config.policy,
        config.inspector_url,
        config.inspector_model,
    )


def get_gateway(config: PrivacyConfig | None = None) -> PrivacyGateway | None:
    """Return the shared gateway, or ``None`` when the feature is not active.

    A malformed rules file raises instead of degrading to "no anonymization":
    silently sending real names because a comma was missing is the one failure
    mode this feature exists to prevent.
    """
    config = config or PrivacyConfig.from_env()
    if not config.active:
        return None

    signature = _signature(config)
    global _cached_gateway, _cached_signature
    with _cache_lock:
        if _cached_gateway is not None and _cached_signature == signature:
            return _cached_gateway

        rules = AnonymizationRules.load(config.rules_path)
        store = MappingStore(config.mapping_path)
        inspector = (
            None
            if config.policy == InspectionPolicy.OFF
            else LocalLlmInspector(
                base_url=config.inspector_url,
                model=config.inspector_model,
                timeout_seconds=config.inspector_timeout,
            )
        )
        gateway = PrivacyGateway(
            anonymizer=Anonymizer(rules=rules, store=store),
            inspector=inspector,
            policy=config.policy,
            audit=AuditLog(config.audit_path, include_text=config.audit_includes_text),
        )
        logger.info(
            "Anonymization gateway active: %d rule(s) from %s, policy=%s, mapping=%s",
            len(rules.matchers),
            config.rules_path,
            config.policy,
            config.mapping_path,
        )
        _cached_gateway = gateway
        _cached_signature = signature
        return gateway


def reset_gateway_cache() -> None:
    """Drop the cached gateway (tests, and after rewriting the rules file)."""
    global _cached_gateway, _cached_signature
    with _cache_lock:
        _cached_gateway = None
        _cached_signature = None
