"""Codex engine status for the per-turn footer.

Fetches the current Codex account and usage / rate-limit data via the
``codex app-server`` JSON-RPC methods ``account/read`` and
``account/rateLimits/read``, then formats them into a compact, Discord-ready
line.

No browser automation, no public REST API: we drive the official client's
local stdio backend over JSON-RPC. The call is read-only and incurs no billing
(it is exactly what ``codex`` itself does every time it starts an interactive
session).

The result is cached per ``codex_command`` with a short TTL so that rapid
successive turns do not each spawn an ``app-server`` process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import os
import shlex
import time
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# JSON-RPC methods exposed by `codex app-server`.
_ACCOUNT_METHOD = "account/read"
_RATE_LIMITS_METHOD = "account/rateLimits/read"

_DEFAULT_TIMEOUT = 15.0
# Successful results are cached this long; rate-limit windows move slowly
# (5h / weekly) so a short cache avoids spawning app-server every turn.
_DEFAULT_TTL = 90.0
# Failures (codex missing, not logged in) are cached for a shorter window so we
# do not hammer a broken setup on every message, but still recover quickly.
_FAIL_TTL = 30.0


async def fetch_codex_rate_limits(
    codex_command: str = "codex",
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict | None:
    """Return rate limits enriched with the current account, or ``None``.

    Spawns ``<codex_command> app-server``, performs the ``initialize``
    handshake, then calls the account and rate-limits methods. The returned
    rate-limit result includes an ``account`` object when ``account/read``
    supplies one. Account lookup failure does not hide otherwise valid usage
    data. Any process/protocol failure yields ``None`` — callers treat that as
    "Codex status unavailable".

    Security: always ``create_subprocess_exec`` (never a shell). ``codex_command``
    comes from trusted configuration, not user input, but is still split with
    ``shlex`` and passed as discrete argv entries.
    """
    parts = shlex.split(codex_command) if codex_command else ["codex"]
    if not parts:
        parts = ["codex"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *parts,
            "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (OSError, ValueError):
        logger.debug("Failed to spawn codex app-server", exc_info=True)
        return None

    async def _exchange() -> dict | None:
        assert proc.stdin is not None and proc.stdout is not None
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "ccdb-engine-status", "version": "1.0.0"}},
        }
        account_read = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": _ACCOUNT_METHOD,
            "params": {"refreshToken": False},
        }
        rate_limits_read = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": _RATE_LIMITS_METHOD,
            "params": None,
        }
        proc.stdin.write((json.dumps(init) + "\n").encode())
        proc.stdin.write((json.dumps(account_read) + "\n").encode())
        proc.stdin.write((json.dumps(rate_limits_read) + "\n").encode())
        await proc.stdin.drain()

        responses: dict[int, dict | None] = {}
        while True:
            line = await proc.stdout.readline()
            if not line:  # EOF
                return None
            try:
                msg = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            response_id = msg.get("id")
            if response_id in (2, 3):
                responses[response_id] = msg.get("result") if "result" in msg else None
            if 2 not in responses or 3 not in responses:
                continue

            rate_limits = responses[3]
            if not isinstance(rate_limits, dict):
                return None
            result = dict(rate_limits)
            account_result = responses[2]
            if isinstance(account_result, dict) and isinstance(account_result.get("account"), dict):
                result["account"] = account_result["account"]
            return result

    try:
        return await asyncio.wait_for(_exchange(), timeout=timeout)
    except (TimeoutError, Exception):
        logger.debug("codex app-server rate-limits exchange failed", exc_info=True)
        return None
    finally:
        with contextlib.suppress(ProcessLookupError):
            proc.terminate()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=3)


def _fmt_pct(snap: dict | None) -> str | None:
    """Return ``"N%"`` from a primary/secondary snapshot, or ``None``."""
    if not isinstance(snap, dict):
        return None
    pct = snap.get("usedPercent")
    if pct is None:
        return None
    try:
        return f"{round(float(pct))}%"
    except (TypeError, ValueError):
        return None


def _window_label(snap: dict | None, fallback: str) -> str:
    """Return a compact quota-window label from its reported duration."""
    if not isinstance(snap, dict):
        return fallback
    duration = snap.get("windowDurationMins")
    if not isinstance(duration, (int, float, str)):
        return fallback
    try:
        minutes = round(float(duration))
    except (TypeError, ValueError, OverflowError):
        return fallback
    if minutes == 300:
        return "5h"
    if minutes == 10080:
        return "7d"
    if minutes > 0 and minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes > 0 and minutes % 60 == 0:
        return f"{minutes // 60}h"
    if minutes > 0:
        return f"{minutes}m"
    return fallback


def _reset_countdown(snap: dict | None, now: float) -> str | None:
    """Return a human-readable duration until the snapshot resets."""
    if not isinstance(snap, dict):
        return None
    resets_at = snap.get("resetsAt")
    if not isinstance(resets_at, (int, float, str)):
        return None
    try:
        seconds = max(0.0, float(resets_at) - now)
        minutes = math.ceil(seconds / 60)
    except (TypeError, ValueError, OverflowError):
        return None

    days, remainder = divmod(minutes, 24 * 60)
    hours, mins = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins or not parts:
        parts.append(f"{mins}m")
    return " ".join(parts)


def _account_label(data: dict) -> str | None:
    """Return a compact, single-line display name or email for the account."""
    account = data.get("account")
    if not isinstance(account, dict):
        return None
    for field in ("displayName", "name", "email"):
        value = account.get(field)
        if not isinstance(value, str):
            continue
        label = " ".join(value.split())
        if label:
            return label[:120]
    return None


def _plan_label(data: dict, rate_limits: dict) -> str | None:
    """Return a normalized subscription plan label from either response."""
    account = data.get("account")
    candidates = [rate_limits.get("planType")]
    if isinstance(account, dict):
        candidates.append(account.get("planType"))
    for value in candidates:
        if not isinstance(value, str):
            continue
        label = " ".join(value.split())
        if label:
            return label[:40]
    return None


def _usage_line(snap: dict | None, fallback_label: str, now: float) -> str | None:
    """Format one rate-limit window as a Discord status row."""
    pct = _fmt_pct(snap)
    if pct is None:
        return None
    line = f"{_window_label(snap, fallback_label)}  used {pct}"
    countdown = _reset_countdown(snap, now)
    if countdown is not None:
        line += f" — resets in {countdown}"
    return line


def format_codex_status_line(
    data: dict | None,
    *,
    show_account: bool = False,
    now: float | None = None,
) -> str | None:
    """Format an ``account/rateLimits/read`` result into Discord status rows.

    Example::

        Codex · prolite subscription (user@example.com)
        5h  used 84% — resets in 28m
        7d  used 58% — resets in 23h 58m

    Returns ``None`` when there is nothing meaningful to show.
    """
    if not isinstance(data, dict):
        return None
    snap = data.get("rateLimits")
    if not isinstance(snap, dict):
        return None

    current_time = time.time() if now is None else now
    rows = [
        row
        for row in (
            _usage_line(snap.get("primary"), "5h", current_time),
            _usage_line(snap.get("secondary"), "7d", current_time),
        )
        if row is not None
    ]
    if not rows:
        return None

    plan = _plan_label(data, snap)
    header = "Codex"
    if plan:
        header += f" · {plan} subscription"
    account = _account_label(data) if show_account else None
    if account:
        header += f" ({account})"
    if snap.get("rateLimitReachedType"):
        header += " ⚠ limit reached"
    return "\n".join([header, *rows])


class CodexStatusProvider:
    """TTL-cached provider of the formatted Codex status line.

    ``fetcher`` and ``clock`` are injectable for testing. In production the
    fetcher is :func:`fetch_codex_rate_limits` and the clock is
    ``time.monotonic``.
    """

    def __init__(
        self,
        codex_command: str = "codex",
        *,
        ttl: float = _DEFAULT_TTL,
        fail_ttl: float = _FAIL_TTL,
        show_account: bool = False,
        fetcher: Callable[[str], Awaitable[dict | None]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._command = codex_command
        self._ttl = ttl
        self._fail_ttl = fail_ttl
        self._show_account = show_account
        self._fetcher = fetcher or (lambda cmd: fetch_codex_rate_limits(cmd))
        self._clock = clock
        self._cached_line: str | None = None
        self._cached_at: float | None = None
        self._cache_was_success = False
        self._lock = asyncio.Lock()

    def _is_fresh(self) -> bool:
        if self._cached_at is None:
            return False
        ttl = self._ttl if self._cache_was_success else self._fail_ttl
        return (self._clock() - self._cached_at) < ttl

    async def get_line(self, *, force: bool = False) -> str | None:
        """Return the cached status line, refreshing it when stale."""
        async with self._lock:
            if not force and self._is_fresh():
                return self._cached_line
            data = await self._fetcher(self._command)
            line = format_codex_status_line(data, show_account=self._show_account)
            self._cached_line = line
            self._cached_at = self._clock()
            self._cache_was_success = line is not None
            return line


# Module-level provider registry keyed by command and account-display mode so
# opt-in and default callers never share a formatted cache entry.
_PROVIDERS: dict[tuple[str, bool], CodexStatusProvider] = {}


def _provider_for(codex_command: str, show_account: bool) -> CodexStatusProvider:
    key = (codex_command, show_account)
    prov = _PROVIDERS.get(key)
    if prov is None:
        prov = CodexStatusProvider(codex_command, show_account=show_account)
        _PROVIDERS[key] = prov
    return prov


def _account_display_enabled() -> bool:
    """Return whether the account identifier is explicitly enabled."""
    value = os.getenv("CCDB_CODEX_STATUS_ACCOUNT", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def get_codex_status_line(
    codex_command: str = "codex",
    *,
    show_account: bool | None = None,
) -> str | None:
    """Convenience entry point used by the per-turn footer (cached)."""
    enabled = _account_display_enabled() if show_account is None else show_account
    return await _provider_for(codex_command, enabled).get_line()
