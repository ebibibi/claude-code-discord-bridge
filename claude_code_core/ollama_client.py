"""A thin async client for Ollama's native API, used by the local backend.

The local backend talks to Ollama through its *OpenAI-compatible* surface
(``/v1``) because that is what the Codex CLI speaks. Everything an operator
needs to *manage* the runtime — which models exist, which are resident in
memory, how big they are, whether they can call tools — lives on Ollama's
*native* API (``/api/tags``, ``/api/ps``, ``/api/show``, …) on the same origin.

This module derives the native origin from the configured ``/v1`` URL, so an
operator only ever configures one address. Every call is read-only except
:func:`pull_model` and :func:`delete_model`, which are the two mutations the
``/ollama`` command exposes.

Design notes:

* ``urllib`` in a worker thread rather than ``aiohttp``. The bot already
  depends on aiohttp, but these calls are rare, one-shot, and easier to reason
  about (and to test) as blocking functions wrapped in ``asyncio.to_thread``.
* Nothing here is ever interpolated into a shell command. Model names are still
  validated with a strict grammar because a bad name should fail before a
  multi-gigabyte download starts, not after.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

__all__ = [
    "OllamaError",
    "OllamaModel",
    "RunningModel",
    "ollama_api_url",
    "validate_ollama_model_name",
    "list_models",
    "running_models",
    "show_model",
    "delete_model",
    "server_version",
    "pull_model",
]

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_PULL_TIMEOUT_SECONDS = 6 * 60 * 60

OLLAMA_MODEL_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*"
    r"(?::[A-Za-z0-9][A-Za-z0-9._-]*)?$"
)

# Codex drives the model entirely through tool calls. A model without this
# capability produces prose where a tool call was required, which reads as
# "the local backend is bad" when it is really "this model cannot act".
REQUIRED_CAPABILITY = "tools"


class OllamaError(RuntimeError):
    """Any failure talking to the Ollama server, with an operator-readable message."""


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


def ollama_api_url(base_url: str, path: str) -> str:
    """Derive a native Ollama API URL from the configured OpenAI-compatible URL.

    The local backend is configured with Ollama's OpenAI-compatible endpoint,
    normally ``http://host:11434/v1``. The management API lives on the same
    origin under ``/api/...``, so only the terminal ``/v1`` is replaced. A
    non-standard prefix (``https://host/ollama/v1``) is preserved.
    """
    parsed = urlsplit(base_url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("CCDB_LOCAL_BASE_URL must be an HTTP(S) URL without credentials")

    prefix = parsed.path.rstrip("/")
    if prefix.endswith("/v1"):
        prefix = prefix[:-3]
    prefix = prefix.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return urlunsplit((parsed.scheme, parsed.netloc, f"{prefix}{suffix}", "", ""))


# ── model records ──────────────────────────────────────────────────


@dataclass(frozen=True)
class OllamaModel:
    """One model present on the server (``/api/tags``)."""

    name: str
    size_bytes: int
    parameter_size: str
    quantization: str
    family: str
    capabilities: tuple[str, ...] = ()
    modified_at: str = ""

    @property
    def size_gb(self) -> float:
        return self.size_bytes / 1_000_000_000

    @property
    def supports_tools(self) -> bool:
        return REQUIRED_CAPABILITY in self.capabilities

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> OllamaModel:
        details = payload.get("details") or {}
        return cls(
            name=str(payload.get("name") or payload.get("model") or "?"),
            size_bytes=int(payload.get("size") or 0),
            parameter_size=str(details.get("parameter_size") or ""),
            quantization=str(details.get("quantization_level") or ""),
            family=str(details.get("family") or ""),
            capabilities=tuple(str(c) for c in (payload.get("capabilities") or ())),
            modified_at=str(payload.get("modified_at") or ""),
        )


@dataclass(frozen=True)
class RunningModel:
    """One model currently resident in memory (``/api/ps``).

    ``size_vram_bytes`` versus ``size_bytes`` is the answer to "is this actually
    on the GPU?" — when they are equal the whole model is on the accelerator;
    when VRAM is lower the remainder is spilling to system RAM and generation
    will be far slower.
    """

    name: str
    size_bytes: int
    size_vram_bytes: int
    context_length: int = 0
    expires_at: str = ""

    @property
    def size_gb(self) -> float:
        return self.size_bytes / 1_000_000_000

    @property
    def vram_gb(self) -> float:
        return self.size_vram_bytes / 1_000_000_000

    @property
    def fully_on_gpu(self) -> bool:
        return self.size_bytes > 0 and self.size_vram_bytes >= self.size_bytes

    @property
    def gpu_percent(self) -> int:
        if self.size_bytes <= 0:
            return 0
        return round(100 * self.size_vram_bytes / self.size_bytes)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RunningModel:
        return cls(
            name=str(payload.get("name") or payload.get("model") or "?"),
            size_bytes=int(payload.get("size") or 0),
            size_vram_bytes=int(payload.get("size_vram") or 0),
            context_length=int(payload.get("context_length") or 0),
            expires_at=str(payload.get("expires_at") or ""),
        )


@dataclass(frozen=True)
class ModelDetail:
    """The subset of ``/api/show`` an operator actually reads."""

    name: str
    capabilities: tuple[str, ...] = ()
    parameter_size: str = ""
    quantization: str = ""
    family: str = ""
    max_context_length: int = 0
    parameters: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def supports_tools(self) -> bool:
        return REQUIRED_CAPABILITY in self.capabilities


def _extract_max_context(model_info: dict[str, Any]) -> int:
    """Pull the architecture's context window out of ``/api/show`` model_info.

    The key is namespaced by architecture (``qwen3moe.context_length``,
    ``gptoss.context_length``, …) so there is no fixed key to read; the
    architecture-prefixed ``*.context_length`` is taken, ignoring RoPE's
    ``original_context_length`` which reports the pre-scaling window.
    """
    best = 0
    for key, value in model_info.items():
        if key.endswith(".context_length") and "original" not in key:
            try:
                best = max(best, int(value))
            except (TypeError, ValueError):
                continue
    return best


# ── transport ──────────────────────────────────────────────────────


def _request_sync(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Perform one blocking JSON request against the Ollama native API."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    request = urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
    except urllib_error.HTTPError as exc:
        detail = ""
        with contextlib.suppress(Exception):  # body is diagnostics only
            detail = exc.read().decode("utf-8", "replace")[:300]
        suffix = f": {detail}" if detail else ""
        raise OllamaError(f"Ollama returned HTTP {exc.code}{suffix}") from exc
    except (urllib_error.URLError, TimeoutError, OSError) as exc:
        raise OllamaError(f"Could not reach the Ollama server: {exc}") from exc

    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OllamaError("Ollama returned a response that is not valid JSON") from exc


async def _request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    return await asyncio.to_thread(
        _request_sync,
        ollama_api_url(base_url, path),
        method=method,
        payload=payload,
        timeout_seconds=timeout_seconds,
    )


# ── operations ─────────────────────────────────────────────────────


async def server_version(base_url: str, *, timeout_seconds: float = 5.0) -> str:
    """Return the Ollama server version, or raise :class:`OllamaError`."""
    result = await _request(base_url, "/api/version", timeout_seconds=timeout_seconds)
    if not isinstance(result, dict):
        raise OllamaError("Unexpected response from /api/version")
    return str(result.get("version") or "unknown")


async def list_models(
    base_url: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> list[OllamaModel]:
    """Return every model installed on the server, largest first."""
    result = await _request(base_url, "/api/tags", timeout_seconds=timeout_seconds)
    if not isinstance(result, dict):
        raise OllamaError("Unexpected response from /api/tags")
    models = [
        OllamaModel.from_payload(item)
        for item in (result.get("models") or [])
        if isinstance(item, dict)
    ]
    return sorted(models, key=lambda m: m.size_bytes, reverse=True)


async def running_models(
    base_url: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> list[RunningModel]:
    """Return the models currently held in memory (empty list is normal)."""
    result = await _request(base_url, "/api/ps", timeout_seconds=timeout_seconds)
    if not isinstance(result, dict):
        raise OllamaError("Unexpected response from /api/ps")
    return [
        RunningModel.from_payload(item)
        for item in (result.get("models") or [])
        if isinstance(item, dict)
    ]


async def show_model(
    base_url: str, model: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> ModelDetail:
    """Return the details of one installed model."""
    normalized = validate_ollama_model_name(model)
    result = await _request(
        base_url,
        "/api/show",
        method="POST",
        payload={"model": normalized},
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(result, dict):
        raise OllamaError("Unexpected response from /api/show")
    details = result.get("details") or {}
    return ModelDetail(
        name=normalized,
        capabilities=tuple(str(c) for c in (result.get("capabilities") or ())),
        parameter_size=str(details.get("parameter_size") or ""),
        quantization=str(details.get("quantization_level") or ""),
        family=str(details.get("family") or ""),
        max_context_length=_extract_max_context(result.get("model_info") or {}),
        parameters=str(result.get("parameters") or ""),
        raw=result,
    )


async def delete_model(
    base_url: str, model: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> None:
    """Delete an installed model, freeing its disk space."""
    normalized = validate_ollama_model_name(model)
    await _request(
        base_url,
        "/api/delete",
        method="DELETE",
        payload={"model": normalized},
        timeout_seconds=timeout_seconds,
    )


async def pull_model(
    base_url: str,
    model: str,
    *,
    timeout_seconds: float = DEFAULT_PULL_TIMEOUT_SECONDS,
) -> None:
    """Pull a model, blocking until the download completes.

    Non-streaming on purpose: the caller is a Discord command that posts once
    when the pull finishes, and a streamed progress feed would mean either
    editing a message thousands of times or holding a partial line buffer for
    hours.
    """
    normalized = validate_ollama_model_name(model)
    result = await _request(
        base_url,
        "/api/pull",
        method="POST",
        payload={"model": normalized, "stream": False},
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(result, dict) or result.get("status") != "success":
        detail = result.get("error") or result.get("status") if isinstance(result, dict) else None
        suffix = f": {detail}" if detail else ""
        raise OllamaError(f"Ollama model pull did not complete successfully{suffix}")
