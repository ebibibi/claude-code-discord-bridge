"""Environment-driven configuration for the anonymization gateway.

Zero-config rule: the feature turns itself on when a rules file exists and off
when it does not. There is nothing to wire up in a consumer's code.

Empty environment variables are treated as *unset*. ``os.environ.get(k, d)``
returns ``""`` when the key exists but is blank, which silently kills defaults;
every read here goes through ``_env`` to avoid that.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["PrivacyConfig", "InspectionPolicy", "GatewayScope"]

DEFAULT_DIR = Path.home() / ".ccdb"
DEFAULT_RULES_NAME = "anonymize-rules.json"
DEFAULT_MAPPING_NAME = "anonymize-mapping.json"
DEFAULT_AUDIT_NAME = "anonymize-audit.jsonl"
DEFAULT_INSPECTOR_URL = "http://127.0.0.1:11434"
DEFAULT_INSPECTOR_MODEL = "qwen3:4b"
DEFAULT_INSPECTOR_TIMEOUT = 30.0


class InspectionPolicy:
    """What to do when the local inspector finds — or cannot look for — leftovers."""

    BLOCK = "block"  # refuse to send; show the operator what was found
    WARN = "warn"  # send anyway, but log and surface the finding
    OFF = "off"  # do not inspect at all (rule-based replacement still runs)

    ALL = (BLOCK, WARN, OFF)


class GatewayScope:
    """Which traffic the gateway sits on.

    ``escalation`` is the default because in the local-first design the agent
    itself runs on a model the operator controls, and anonymizing that traffic
    buys nothing while making the local model reason about aliases instead of
    real names. Only the deliberate hop to an external vendor needs the
    gateway.

    ``all`` restores the original behaviour — every backend wrapped — for
    deployments whose agent still runs against a vendor by default.
    """

    ESCALATION = "escalation"
    ALL_TRAFFIC = "all"

    ALL = (ESCALATION, ALL_TRAFFIC)


def _env(name: str) -> str | None:
    """Read an env var, treating blank as unset."""
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class PrivacyConfig:
    """Resolved gateway settings."""

    rules_path: Path
    mapping_path: Path
    audit_path: Path | None
    inspector_url: str = DEFAULT_INSPECTOR_URL
    inspector_model: str = DEFAULT_INSPECTOR_MODEL
    inspector_timeout: float = DEFAULT_INSPECTOR_TIMEOUT
    policy: str = InspectionPolicy.BLOCK
    audit_includes_text: bool = True
    scope: str = GatewayScope.ESCALATION
    explicitly_disabled: bool = False

    @property
    def rules_exist(self) -> bool:
        return self.rules_path.is_file()

    @property
    def active(self) -> bool:
        """The gateway runs only when it has rules and was not switched off."""
        return not self.explicitly_disabled and self.rules_exist

    @property
    def wraps_backends(self) -> bool:
        """True when ordinary chat traffic goes through the gateway too."""
        return self.active and self.scope == GatewayScope.ALL_TRAFFIC

    @classmethod
    def from_env(cls) -> PrivacyConfig:
        rules_path = Path(_env("CCDB_ANONYMIZE_RULES") or DEFAULT_DIR / DEFAULT_RULES_NAME)
        base_dir = rules_path.parent

        mapping_raw = _env("CCDB_ANONYMIZE_MAPPING")
        mapping_path = Path(mapping_raw) if mapping_raw else base_dir / DEFAULT_MAPPING_NAME

        if _env_bool("CCDB_ANONYMIZE_AUDIT_ENABLED", True):
            audit_raw = _env("CCDB_ANONYMIZE_AUDIT")
            audit_path: Path | None = (
                Path(audit_raw) if audit_raw else base_dir / DEFAULT_AUDIT_NAME
            )
        else:
            audit_path = None

        policy = (_env("CCDB_ANONYMIZE_POLICY") or InspectionPolicy.BLOCK).lower()
        if policy not in InspectionPolicy.ALL:
            logger.warning(
                "Unknown CCDB_ANONYMIZE_POLICY=%r; falling back to %r",
                policy,
                InspectionPolicy.BLOCK,
            )
            policy = InspectionPolicy.BLOCK

        timeout_raw = _env("CCDB_ANONYMIZE_INSPECTOR_TIMEOUT")
        try:
            timeout = float(timeout_raw) if timeout_raw else DEFAULT_INSPECTOR_TIMEOUT
        except ValueError:
            logger.warning("Invalid CCDB_ANONYMIZE_INSPECTOR_TIMEOUT=%r", timeout_raw)
            timeout = DEFAULT_INSPECTOR_TIMEOUT

        scope = (_env("CCDB_ANONYMIZE_SCOPE") or GatewayScope.ESCALATION).lower()
        if scope not in GatewayScope.ALL:
            logger.warning(
                "Unknown CCDB_ANONYMIZE_SCOPE=%r; falling back to %r",
                scope,
                GatewayScope.ESCALATION,
            )
            scope = GatewayScope.ESCALATION

        return cls(
            rules_path=rules_path,
            mapping_path=mapping_path,
            audit_path=audit_path,
            inspector_url=_env("CCDB_ANONYMIZE_INSPECTOR_URL") or DEFAULT_INSPECTOR_URL,
            inspector_model=_env("CCDB_ANONYMIZE_INSPECTOR_MODEL") or DEFAULT_INSPECTOR_MODEL,
            inspector_timeout=timeout,
            policy=policy,
            audit_includes_text=_env_bool("CCDB_ANONYMIZE_AUDIT_TEXT", True),
            scope=scope,
            explicitly_disabled=not _env_bool("CCDB_ANONYMIZE", True),
        )
