"""Factory for SessionBackend instances.

Holds the static configuration needed to construct ClaudeRunner or
CodexRunner instances on demand. Used by ClaudeChatCog (and friends)
to spawn a fresh runner per Discord thread whenever the user issues
a chat message.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

from claude_code_core.backend import create_backend

if TYPE_CHECKING:
    from claude_code_core.backend import SessionBackend

logger = logging.getLogger(__name__)


# Sensible per-backend defaults (mirror the CLIs own defaults so users
# do not need to pick a model just to try a backend).
#
# ``codex`` is intentionally ``None``: when no model is configured we omit
# ``--model`` entirely so the Codex CLI uses its own default (the ``model``
# key in ~/.codex/config.toml, currently gpt-5.6-sol). Hard-coding a version
# here only goes stale as the Codex console default moves.
DEFAULT_MODEL: dict[str, str | None] = {"claude": "sonnet", "codex": None}
DEFAULT_COMMAND = {"claude": "claude", "codex": "codex"}
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def parse_codex_model_profiles(raw: str) -> dict[str, str]:
    """Parse ``model=profile`` pairs from CCDB_CODEX_MODEL_PROFILES."""
    profiles: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        model, separator, profile = entry.partition("=")
        model = model.strip()
        profile = profile.strip()
        if (
            not separator
            or not _MODEL_ID_RE.fullmatch(model)
            or not _PROFILE_ID_RE.fullmatch(profile)
        ):
            raise ValueError(f"Invalid CCDB_CODEX_MODEL_PROFILES entry: {entry!r}")
        profiles[model] = profile
    return profiles


def usable_codex_model_profiles(
    profiles: dict[str, str],
    *,
    env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return model/profile mappings whose local Codex setup is usable.

    A mapped model is advertised by ``/model`` only when its named profile
    exists, its optional model catalog contains the model, and the provider's
    declared credential environment variable is present. This deliberately
    avoids a remote request on every Discord autocomplete keystroke while still
    hiding stale mappings after a profile, catalog, or credential is removed.
    """
    if not profiles:
        return {}

    current_env = os.environ if env is None else env
    home = Path(current_env.get("HOME", str(Path.home())))
    codex_home = Path(current_env.get("CODEX_HOME", str(home / ".codex"))).expanduser()
    base_config = _load_toml(codex_home / "config.toml")

    usable: dict[str, str] = {}
    for model, profile in profiles.items():
        profile_config = _load_toml(codex_home / f"{profile}.config.toml")
        if not profile_config:
            configured_profiles = base_config.get("profiles")
            if isinstance(configured_profiles, dict):
                candidate = configured_profiles.get(profile)
                if isinstance(candidate, dict):
                    profile_config = candidate
        if not profile_config:
            continue

        provider = profile_config.get("model_provider") or base_config.get("model_provider")
        if isinstance(provider, str) and provider not in {"openai", "chatgpt"}:
            provider_config = _provider_config(profile_config, base_config, provider)
            if provider_config is None:
                continue
            env_key = provider_config.get("env_key")
            if isinstance(env_key, str) and env_key and not current_env.get(env_key):
                continue

        catalog_value = profile_config.get("model_catalog_json") or base_config.get(
            "model_catalog_json"
        )
        if isinstance(catalog_value, str) and catalog_value:
            catalog_path = Path(catalog_value).expanduser()
            if not catalog_path.is_absolute():
                catalog_path = codex_home / catalog_path
            if not _catalog_contains_model(catalog_path, model):
                continue

        usable[model] = profile
    return usable


def _load_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _provider_config(
    profile_config: dict[str, object],
    base_config: dict[str, object],
    provider: str,
) -> dict[str, object] | None:
    for config in (profile_config, base_config):
        providers = config.get("model_providers")
        if not isinstance(providers, dict):
            continue
        candidate = providers.get(provider)
        if isinstance(candidate, dict):
            return candidate
    return None


def _catalog_contains_model(path: Path, model: str) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    models = data.get("models") if isinstance(data, dict) else data
    if not isinstance(models, list):
        return False
    return any(
        isinstance(item, dict) and model in {item.get("slug"), item.get("id")} for item in models
    )


class BackendFactory:
    """Builds SessionBackend instances on demand from static configuration."""

    def __init__(
        self,
        *,
        claude_command: str,
        codex_command: str,
        permission_mode: str,
        working_dir: str | None,
        timeout_seconds: int,
        dangerously_skip_permissions: bool,
        allowed_tools: list[str] | None,
        append_system_prompt: str | None,
        effort: str | None,
        codex_model_profiles: dict[str, str] | None = None,
        api_port: int | None = None,
        api_secret: str | None = None,
    ) -> None:
        self.claude_command = claude_command or DEFAULT_COMMAND["claude"]
        self.codex_command = codex_command or DEFAULT_COMMAND["codex"]
        self.permission_mode = permission_mode
        self.working_dir = working_dir
        self.timeout_seconds = timeout_seconds
        self.dangerously_skip_permissions = dangerously_skip_permissions
        self.allowed_tools = allowed_tools
        self.append_system_prompt = append_system_prompt
        self.effort = effort
        self.codex_model_profiles = dict(codex_model_profiles or {})
        self.api_port = api_port
        self.api_secret = api_secret

    def command_for(self, backend: str) -> str:
        if backend == "claude":
            return self.claude_command
        if backend == "codex":
            return self.codex_command
        raise ValueError(f"Unknown backend: {backend!r}")

    def default_model_for(self, backend: str) -> str | None:
        """Return the built-in default model, or ``None`` to defer to the CLI.

        ``None`` (codex) means "do not pass ``--model``" so the Codex CLI uses
        its own configured default.
        """
        return DEFAULT_MODEL.get(backend, DEFAULT_MODEL["claude"])

    def build(
        self,
        *,
        backend: str,
        model: str | None = None,
        thread_id: int | None = None,
    ) -> SessionBackend:
        """Construct a fresh SessionBackend for the given backend/model."""
        chosen_model = model or self.default_model_for(backend)
        command = self.command_for(backend)
        kwargs: dict[str, object] = {
            "command": command,
            "permission_mode": self.permission_mode,
            "working_dir": self.working_dir,
            "timeout_seconds": self.timeout_seconds,
            "dangerously_skip_permissions": self.dangerously_skip_permissions,
            "allowed_tools": self.allowed_tools,
        }
        if thread_id is not None:
            kwargs["thread_id"] = thread_id
        # ``append_system_prompt`` and the env-level ``effort`` are Claude-only
        # defaults. We deliberately do NOT forward them to Codex: Codex effort
        # is resolved per-backend from BackendSettings at spawn time (and its
        # valid values differ — e.g. Claude's "max" is not a Codex level).
        if backend == "claude":
            if self.append_system_prompt is not None:
                kwargs["append_system_prompt"] = self.append_system_prompt
            if self.effort is not None:
                kwargs["effort"] = self.effort
        elif chosen_model is not None:
            profile = self.codex_model_profiles.get(chosen_model)
            if profile is not None:
                kwargs["profile"] = profile
        if self.api_port is not None:
            kwargs["api_port"] = self.api_port
        if self.api_secret is not None:
            kwargs["api_secret"] = self.api_secret
        runner = create_backend(backend=backend, model=chosen_model, **kwargs)
        logger.debug("Built %s runner (model=%s, thread_id=%s)", backend, chosen_model, thread_id)
        return runner

    def usable_codex_model_profiles(self) -> dict[str, str]:
        """Return configured Codex model routes safe to advertise right now."""
        return usable_codex_model_profiles(self.codex_model_profiles)
