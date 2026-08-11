"""Z.ai backend implemented through the Anthropic-compatible Claude Code CLI."""

from __future__ import annotations

import os
from typing import Any

from .runner import ClaudeRunner

ZAI_ANTHROPIC_BASE_URL = "https://api.z.ai/api/anthropic"


class ZaiRunner(ClaudeRunner):
    """Claude Code runner isolated to Z.ai credentials and endpoint.

    Z.ai speaks the Anthropic Messages API, so the same Claude Code CLI works
    unchanged once its environment points at Z.ai. The isolation is the point:
    a Z.ai thread must never inherit (or fall back to) direct-Anthropic
    credentials, so the inherited ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN``
    are popped before the Z.ai endpoint and credential file are applied.
    """

    backend_name = "zai"

    def __init__(self, *, env_file: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.env_file = env_file or os.environ.get("CCDB_ZAI_ENV_FILE")

    def _clone_extra_kwargs(self) -> dict[str, Any]:
        return {"env_file": self.env_file}

    def _build_env(self) -> dict[str, str]:
        env = super()._build_env()

        # Never reuse credentials intended for the direct Anthropic backend.
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)

        # Fail toward Z.ai (an auth error when no key is configured), never
        # silently toward Anthropic. The dedicated file may override the URL
        # for a regional Z.ai endpoint.
        env["ANTHROPIC_BASE_URL"] = ZAI_ANTHROPIC_BASE_URL
        self._merge_env_file(env, self.env_file)
        env.pop("CCDB_ZAI_ENV_FILE", None)
        return env
