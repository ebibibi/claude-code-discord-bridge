"""Detect which Claude API endpoint a CLI subprocess will talk to.

The Claude Code CLI selects its API endpoint purely from environment
variables. :func:`detect_api_provider` maps the *final* subprocess
environment (as produced by ``ClaudeRunner._build_env()``) to a short,
human-readable label, so the bridge can surface "which API am I using right
now" in Discord after every session.

Resolution order mirrors the Claude Code CLI's own precedence: the Bedrock
and Vertex flags win over a custom base URL, which in turn wins over the
default direct Anthropic API.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

# Values Claude Code treats as "enabled" for its boolean backend flags.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _is_enabled(env: Mapping[str, str], key: str) -> bool:
    """Return True when *env[key]* is a recognised truthy flag value."""
    return env.get(key, "").strip().lower() in _TRUTHY


def detect_api_provider(env: Mapping[str, str]) -> str:
    """Return a short label for the Claude API endpoint *env* selects.

    Args:
        env: The subprocess environment the CLI will run with. Pass the
            output of ``ClaudeRunner._build_env()`` so CLI env overlays and
            systemd-provided variables are reflected accurately.

    Returns:
        A concise label such as ``"Anthropic API (direct)"``,
        ``"AWS Bedrock (us-east-1)"``, or ``"Azure AI Foundry (resource)"``.
    """
    if _is_enabled(env, "CLAUDE_CODE_USE_BEDROCK"):
        region = (env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "").strip()
        return f"AWS Bedrock ({region})" if region else "AWS Bedrock"

    if _is_enabled(env, "CLAUDE_CODE_USE_VERTEX"):
        region = (env.get("CLOUD_ML_REGION") or "").strip()
        return f"Google Vertex AI ({region})" if region else "Google Vertex AI"

    # Azure AI Foundry serves Claude models in some deployments.
    if _is_enabled(env, "CLAUDE_CODE_USE_FOUNDRY"):
        resource = (env.get("ANTHROPIC_FOUNDRY_RESOURCE") or "").strip()
        return f"Azure AI Foundry ({resource})" if resource else "Azure AI Foundry"

    base_url = (env.get("ANTHROPIC_BASE_URL") or "").strip()
    if base_url:
        host = urlparse(base_url).hostname or base_url
        return f"Custom endpoint ({host})"

    return "Anthropic API (direct)"
