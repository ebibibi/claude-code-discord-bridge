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


def format_codex_status_line(
    data: dict | None,
    *,
    show_account: bool = False,
) -> str | None:
    """Format a ``account/rateLimits/read`` result into one Discord line.

    Example: ``🤖 Codex (user@example.com): 5h 1% · 週次 8% · クレジット 0``.
    Returns ``None`` when there is nothing meaningful to show.
    """
    if not isinstance(data, dict):
        return None
    snap = data.get("rateLimits")
    if not isinstance(snap, dict):
        return None

    segments: list[str] = []
    primary = _fmt_pct(snap.get("primary"))
    if primary is not None:
        segments.append(f"5h {primary}")
    secondary = _fmt_pct(snap.get("secondary"))
    if secondary is not None:
        segments.append(f"週次 {secondary}")

    credit_info = snap.get("credits")
    if isinstance(credit_info, dict):
        if credit_info.get("unlimited"):
            segments.append("クレジット 無制限")
        elif credit_info.get("balance") is not None:
            segments.append(f"クレジット {credit_info.get('balance')}")

    if not segments:
        return None

    plan = snap.get("planType")
    suffix = f" ({plan})" if plan else ""
    reached = snap.get("rateLimitReachedType")
    warn = " ⚠ 上限到達" if reached else ""
    account = _account_label(data) if show_account else None
    account_suffix = f" ({account})" if account else ""
    return f"\U0001f916 Codex{account_suffix}: {' · '.join(segments)}{suffix}{warn}"


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
