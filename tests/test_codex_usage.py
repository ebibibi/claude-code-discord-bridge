"""Tests for Codex rate-limit fetching and formatting."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from claude_discord.discord_ui.codex_usage import build_codex_usage_lines, fetch_codex_rate_limits


class _DummyStdin:
    def __init__(self) -> None:
        self.buffer = bytearray()

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


class _DummyStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = [line.encode("utf-8") for line in lines]

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _DummyProcess:
    def __init__(self, lines: list[str]) -> None:
        self.stdin = _DummyStdin()
        self.stdout = _DummyStdout(lines)
        self.returncode = None
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    async def wait(self) -> int:
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode


class TestFetchCodexRateLimits:
    async def test_reads_rate_limits_via_app_server(self) -> None:
        process = _DummyProcess(
            [
                json.dumps({"id": 1, "result": {"userAgent": "probe"}}) + "\n",
                json.dumps(
                    {
                        "id": 2,
                        "result": {
                            "rateLimits": {
                                "limitId": "codex",
                                "primary": {"usedPercent": 24, "windowDurationMins": 300},
                                "secondary": {"usedPercent": 11, "windowDurationMins": 10080},
                            }
                        },
                    }
                )
                + "\n",
            ]
        )

        with patch(
            "claude_discord.discord_ui.codex_usage.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ):
            result = await fetch_codex_rate_limits("codex", use_cache=False)

        assert result is not None
        assert result["rateLimits"]["primary"]["usedPercent"] == 24

        sent = process.stdin.buffer.decode("utf-8")
        assert '"method": "initialize"' in sent
        assert '"method": "account/rateLimits/read"' in sent


class TestBuildCodexUsageLines:
    def test_formats_primary_and_secondary_windows(self) -> None:
        payload = {
            "rateLimits": {
                "primary": {
                    "usedPercent": 24,
                    "windowDurationMins": 300,
                    "resetsAt": 4_102_444_800,
                },
                "secondary": {
                    "usedPercent": 11,
                    "windowDurationMins": 10080,
                    "resetsAt": 4_102_531_200,
                },
            }
        }

        lines = build_codex_usage_lines(payload, now=4_102_441_200)

        assert any("5h" in line and "24%" in line for line in lines)
        assert any("7d" in line and "11%" in line for line in lines)
