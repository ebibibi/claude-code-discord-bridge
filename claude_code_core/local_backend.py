"""Local-model backend: the Codex CLI driven by a model on your own hardware.

The point of this backend is a claim that can be checked: while a thread runs
locally, nothing about it reaches a vendor. Pointing the CLI at a local model
is *not* enough to make that true — measured on codex-cli 0.145.0, a run
configured entirely against a local endpoint still opened a connection to
``chatgpt.com`` for the startup update check and analytics, and it did so even
with an empty ``CODEX_HOME`` and no credentials.

So ccdb does not reuse the user's ``~/.codex``. It generates and owns a
separate ``CODEX_HOME`` whose ``config.toml`` points at the local endpoint and
switches both callers-home off. Measured again with that config, the only
endpoint contacted was the local model.

Two consequences worth keeping in mind:

* The guarantee is **measured, not enforced**. A future CLI version could add a
  new call home. ``verify_quiet_settings()`` re-checks the settings we know
  about on every spawn, and the docs say to re-measure after a CLI upgrade.
* The check is structural, so it works the same on Linux, macOS and Windows.
  An OS-level egress rule would be stronger and is not portable; for a
  framework that ships to other people, the config ccdb controls is the right
  trade.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlparse, urlsplit, urlunsplit

from .codex_runner import CodexRunner

logger = logging.getLogger(__name__)

__all__ = [
    "LocalModelConfig",
    "LocalCodexRunner",
    "build_local_config_toml",
    "ensure_codex_home",
    "ollama_pull_url",
    "pull_ollama_model",
    "validate_ollama_model_name",
    "verify_quiet_settings",
]

DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "gpt-oss:120b"
PROVIDER_ID = "ccdb_local"
DEFAULT_OLLAMA_PULL_TIMEOUT_SECONDS = 6 * 60 * 60
OLLAMA_MODEL_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*"
    r"(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$"
)

# Settings that keep a local run local. Each maps to the TOML line that must be
# present in the generated config; verify_quiet_settings() reports any that are
# missing rather than assuming the file is still what we wrote.
REQUIRED_QUIET_SETTINGS: tuple[tuple[str, str], ...] = (
    ("check_for_update_on_startup", "check_for_update_on_startup = false"),
    ("analytics", "[analytics]\nenabled = false"),
)


def _env(name: str) -> str | None:
    """Read an env var, treating blank as unset."""
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


@dataclass(frozen=True)
class LocalModelConfig:
    """Where the local model lives and which model to ask for."""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    codex_home: Path | None = None

    @property
    def resolved_codex_home(self) -> Path:
        return self.codex_home or Path.home() / ".ccdb" / "local-codex-home"

    @property
    def endpoint_host(self) -> str:
        return urlparse(self.base_url).hostname or self.base_url

    @classmethod
    def from_env(cls) -> LocalModelConfig:
        home = _env("CCDB_LOCAL_CODEX_HOME")
        return cls(
            base_url=_env("CCDB_LOCAL_BASE_URL") or DEFAULT_BASE_URL,
            model=_env("CCDB_LOCAL_MODEL") or DEFAULT_MODEL,
            codex_home=Path(home) if home else None,
        )


def validate_ollama_model_name(model: str) -> str:
    """Validate and normalize a user-provided Ollama model identifier.

    Model names are sent as JSON, never interpolated into a shell command. The
    strict grammar still rejects whitespace, control characters, URL syntax,
    and accidentally pasted prose before a long-running pull begins.
    """
    normalized = model.strip()
    if (
        not normalized
        or len(normalized) > 255
        or OLLAMA_MODEL_NAME_PATTERN.fullmatch(normalized) is None
    ):
        raise ValueError(
            "Invalid Ollama model name. Use letters, numbers, '.', '_', '-', '/', "
            "and one optional ':tag'."
        )
    return normalized


def ollama_pull_url(base_url: str) -> str:
    """Derive Ollama's native ``/api/pull`` URL from the configured API URL.

    The local backend uses Ollama's OpenAI-compatible endpoint, normally
    ``http://host:11434/v1``. Pulling a model uses Ollama's native API on the
    same origin, so only the terminal ``/v1`` is replaced.
    """
    parsed = urlsplit(base_url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("CCDB_LOCAL_BASE_URL must be an HTTP(S) URL without credentials")

    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    prefix = path.rstrip("/")
    pull_path = f"{prefix}/api/pull" if prefix else "/api/pull"
    return urlunsplit((parsed.scheme, parsed.netloc, pull_path, "", ""))


def _pull_ollama_model_sync(
    model: str,
    *,
    config: LocalModelConfig,
    timeout_seconds: float,
) -> None:
    """Perform one blocking, non-streaming Ollama pull request."""
    payload = json.dumps({"model": model, "stream": False}).encode("utf-8")
    request = urllib_request.Request(
        ollama_pull_url(config.base_url),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
    except (urllib_error.HTTPError, urllib_error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Ollama model pull request failed: {exc}") from exc

    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Ollama returned an invalid response to the model pull request") from exc

    if not isinstance(result, dict) or result.get("status") != "success":
        detail = result.get("error") or result.get("status") if isinstance(result, dict) else None
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"Ollama model pull did not complete successfully{suffix}")


async def pull_ollama_model(
    model: str,
    *,
    config: LocalModelConfig | None = None,
    timeout_seconds: float = DEFAULT_OLLAMA_PULL_TIMEOUT_SECONDS,
) -> None:
    """Pull an Ollama model without blocking the Discord event loop."""
    normalized = validate_ollama_model_name(model)
    await asyncio.to_thread(
        _pull_ollama_model_sync,
        normalized,
        config=config or LocalModelConfig.from_env(),
        timeout_seconds=timeout_seconds,
    )


def build_local_config_toml(config: LocalModelConfig) -> str:
    """Render the ``config.toml`` for the ccdb-owned CODEX_HOME.

    ``wire_api = "responses"`` is required: codex-cli dropped support for
    ``chat`` completions, and Ollama does serve ``/v1/responses``.
    """
    return f"""# Generated by ccdb — do not edit. Regenerated on every bot start.
# Local-model backend: this CODEX_HOME is deliberately separate from ~/.codex
# so a local thread cannot pick up cloud credentials, and so the two settings
# below cannot be undone by a change to the user's own Codex config.
model = "{config.model}"
model_provider = "{PROVIDER_ID}"

# Keep local runs local. Measured on codex-cli 0.145.0: with these two enabled,
# a fully local run still contacts chatgpt.com. With them off, the only
# endpoint contacted is the local model. Re-measure after a CLI upgrade.
check_for_update_on_startup = false

[analytics]
enabled = false

[model_providers.{PROVIDER_ID}]
name = "ccdb local model"
base_url = "{config.base_url}"
wire_api = "responses"
"""


def ensure_codex_home(config: LocalModelConfig) -> Path:
    """Create/refresh the ccdb-owned CODEX_HOME and return its path.

    Rewritten whenever the content differs, so an edited or stale file cannot
    quietly survive — the generated config is the source of truth.
    """
    home = config.resolved_codex_home
    home.mkdir(parents=True, exist_ok=True)
    target = home / "config.toml"
    desired = build_local_config_toml(config)
    try:
        current = target.read_text(encoding="utf-8")
    except OSError:
        current = None
    if current != desired:
        target.write_text(desired, encoding="utf-8")
        logger.info("Wrote local-model Codex config: %s", target)
    return home


def verify_quiet_settings(codex_home: Path) -> list[str]:
    """Return the names of the local-only settings that are NOT in place.

    An empty list means every setting we know about is present. This is a
    structural check of a file ccdb wrote, not proof that the CLI stays
    offline — see the module docstring.
    """
    target = Path(codex_home) / "config.toml"
    try:
        content = target.read_text(encoding="utf-8")
    except OSError:
        return [name for name, _ in REQUIRED_QUIET_SETTINGS]
    return [name for name, snippet in REQUIRED_QUIET_SETTINGS if snippet not in content]


class LocalCodexRunner(CodexRunner):
    """Codex CLI pinned to a local model through a ccdb-owned CODEX_HOME."""

    def __init__(
        self,
        *args: object,
        local_config: LocalModelConfig | None = None,
        **kwargs: object,
    ) -> None:
        self.local_config = local_config or LocalModelConfig.from_env()
        kwargs.setdefault("model", self.local_config.model)
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def _build_env(self) -> dict[str, str]:
        env = super()._build_env()
        home = ensure_codex_home(self.local_config)
        missing = verify_quiet_settings(home)
        if missing:
            # Fail loudly rather than run a "local" thread that phones home.
            raise RuntimeError(
                "Refusing to start the local backend: "
                f"{', '.join(missing)} missing from {home / 'config.toml'}. "
                "Without these the CLI contacts its vendor even when the model "
                "is local."
            )
        env["CODEX_HOME"] = str(home)
        # Any cloud credentials in the ambient environment would defeat the
        # point of the separate CODEX_HOME.
        for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY"):
            env.pop(key, None)
        return env

    def clone(self, **kwargs: object) -> LocalCodexRunner:
        cloned = super().clone(**kwargs)  # type: ignore[arg-type]
        return LocalCodexRunner(
            command=cloned.command,
            model=cloned.model,
            permission_mode=cloned.permission_mode,
            working_dir=cloned.working_dir,
            timeout_seconds=cloned.timeout_seconds,
            dangerously_skip_permissions=cloned.dangerously_skip_permissions,
            allowed_tools=cloned.allowed_tools,
            api_port=cloned.api_port,
            api_secret=cloned.api_secret,
            thread_id=cloned.thread_id,
            append_system_prompt=cloned.append_system_prompt,
            effort=cloned.effort,
            local_config=self.local_config,
        )

    def describe_api(self) -> str:
        return f"Local model ({self.local_config.endpoint_host})"
