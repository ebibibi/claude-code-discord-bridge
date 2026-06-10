"""Helpers for fetching and formatting Codex rate-limit usage."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0
_CACHE_MAX_AGE_SECONDS = 60
_CACHE_PATH = Path("/tmp/codex/statusline-usage-cache.json")


def _progress_bar(percent: int, width: int = 10) -> str:
    filled = round((max(0, min(100, percent)) / 100) * width)
    return "█" * filled + "░" * (width - filled)


def _format_countdown(resets_at: int | None, now: int | None = None) -> str:
    if resets_at is None:
        return "reset unknown"
    current = int(time.time()) if now is None else now
    remaining = resets_at - current
    if remaining <= 0:
        return "resetting now"
    hours, rem = divmod(remaining, 3600)
    minutes = rem // 60
    if hours > 0:
        return f"resets in {hours}h {minutes}m"
    return f"resets in {minutes}m"


def _window_label(window: dict[str, Any], fallback: str) -> str:
    mins = window.get("windowDurationMins")
    if mins == 300:
        return "⏱ 5h"
    if mins == 10080:
        return "📅 7d"
    return fallback


def build_codex_usage_lines(payload: dict[str, Any], now: int | None = None) -> list[str]:
    """Render Codex usage payload into Discord-friendly text lines."""
    snapshot = payload.get("rateLimits") or {}
    lines: list[str] = []
    for key, fallback in (("primary", "⏱ primary"), ("secondary", "📅 secondary")):
        window = snapshot.get(key)
        if not isinstance(window, dict):
            continue
        used = int(window.get("usedPercent", 0))
        label = _window_label(window, fallback)
        countdown = _format_countdown(window.get("resetsAt"), now=now)
        lines.append(f"{label} `{_progress_bar(used)}` **{used}%** — {countdown}")
    return lines


def _load_cache(max_age_seconds: int) -> dict[str, Any] | None:
    try:
        raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    fetched_at = raw.get("fetched_at")
    data = raw.get("data")
    if not isinstance(fetched_at, (int, float)) or not isinstance(data, dict):
        return None
    if time.time() - fetched_at > max_age_seconds:
        return None
    return data


def _write_cache(data: dict[str, Any]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps({"fetched_at": time.time(), "data": data}),
            encoding="utf-8",
        )
    except OSError:
        logger.debug("Failed to write Codex usage cache", exc_info=True)


async def fetch_codex_rate_limits(
    command: str = "codex",
    *,
    timeout: float = _TIMEOUT_SECONDS,
    use_cache: bool = True,
    cache_max_age_seconds: int = _CACHE_MAX_AGE_SECONDS,
) -> dict[str, Any] | None:
    """Fetch Codex account rate limits via the app-server stdio RPC."""
    if use_cache:
        cached = _load_cache(cache_max_age_seconds)
        if cached is not None:
            return cached

    process = await asyncio.create_subprocess_exec(
        command,
        "app-server",
        "--listen",
        "stdio://",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def _send(payload: dict[str, Any]) -> None:
        if process.stdin is None:
            raise RuntimeError("Codex app-server stdin unavailable")
        process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
        await process.stdin.drain()

    result: dict[str, Any] | None = None
    deadline = time.monotonic() + timeout
    try:
        await _send(
            {
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "ccdb", "version": "1.0"}},
            }
        )
        await _send({"id": 2, "method": "account/rateLimits/read", "params": None})

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for Codex rate limits")
            if process.stdout is None:
                break
            line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
            if not line:
                break
            try:
                message = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            if message.get("id") == 2 and isinstance(message.get("result"), dict):
                result = message["result"]
                break
    except (TimeoutError, OSError, RuntimeError):
        logger.debug("Failed to fetch Codex rate limits", exc_info=True)
        result = None
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.returncode is None:
            process.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=1.0)
        if process.returncode is None:
            process.kill()
            with contextlib.suppress(Exception):
                await process.wait()

    if result is not None and use_cache:
        _write_cache(result)
    return result
