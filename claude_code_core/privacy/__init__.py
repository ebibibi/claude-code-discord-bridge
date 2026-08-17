"""Anonymization gateway: local, deterministic, reversible.

Rule-based replacement happens on this machine, a local model checks for
leftovers, and only then does the text reach an external CLI (Claude Code,
Codex, ...). Answers are restored on the way back.

Design rules, in order of importance:

1. **Rules replace, models inspect.** A model that rewrites text produces a
   different result every run, and a different result cannot be restored.
2. **The mapping table never leaves the machine.** It is the only thing that
   can undo the replacement.
3. **Absent rules mean the feature is off**, and a *broken* rules file is an
   error — never a silent downgrade to sending real names.
"""

from __future__ import annotations

from .answerability import AnswerabilityJudge, AnswerabilityVerdict, get_judge
from .audit import AuditLog
from .backend import AnonymizingBackend
from .config import GatewayScope, InspectionPolicy, PrivacyConfig
from .engine import AnonymizationResult, Anonymizer, Replacement
from .gateway import GuardOutcome, PrivacyGateway, get_gateway, reset_gateway_cache
from .inspector import InspectionResult, LocalLlmInspector, Suspect
from .mapping import MappingStore
from .rules import AnonymizationRules, Category, Matcher, RulesError

__all__ = [
    "AnonymizationResult",
    "AnonymizationRules",
    "Anonymizer",
    "AnonymizingBackend",
    "AnswerabilityJudge",
    "AnswerabilityVerdict",
    "AuditLog",
    "Category",
    "GatewayScope",
    "GuardOutcome",
    "InspectionPolicy",
    "InspectionResult",
    "LocalLlmInspector",
    "MappingStore",
    "Matcher",
    "PrivacyConfig",
    "PrivacyGateway",
    "Replacement",
    "RulesError",
    "Suspect",
    "get_gateway",
    "get_judge",
    "reset_gateway_cache",
]
