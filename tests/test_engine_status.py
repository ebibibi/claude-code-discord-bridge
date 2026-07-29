"""Tests for the Codex engine status footer helpers."""

from __future__ import annotations

import pytest

from claude_discord.discord_ui.engine_status import (
    CodexStatusProvider,
    _account_display_enabled,
    format_codex_status_line,
)

# Representative `account/rateLimits/read` result (trimmed to what we read).
SAMPLE = {
    "account": {
        "type": "chatgpt",
        "email": "user@example.com",
        "planType": "prolite",
    },
    "rateLimits": {
        "limitId": "codex",
        "primary": {"usedPercent": 1, "windowDurationMins": 300, "resetsAt": 1782198285},
        "secondary": {"usedPercent": 8, "windowDurationMins": 10080, "resetsAt": 1782361421},
        "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
        "planType": "prolite",
        "rateLimitReachedType": None,
    },
}


class TestFormat:
    def test_basic_line(self) -> None:
        line = format_codex_status_line(SAMPLE)
        assert line is not None
        assert "Codex" in line
        assert "user@example.com" not in line
        assert "5h 1%" in line
        assert "週次 8%" in line
        assert "クレジット 0" in line
        assert "(prolite)" in line

    def test_account_email_is_opt_in(self) -> None:
        line = format_codex_status_line(SAMPLE, show_account=True)

        assert line is not None
        assert "Codex (user@example.com)" in line

    def test_prefers_account_name_over_email(self) -> None:
        data = {
            "account": {
                "displayName": "  Example   User  ",
                "email": "user@example.com",
            },
            "rateLimits": {"primary": {"usedPercent": 5}},
        }

        line = format_codex_status_line(data, show_account=True)

        assert line is not None
        assert "Codex (Example User)" in line
        assert "user@example.com" not in line

    def test_missing_account_keeps_usage_line(self) -> None:
        data = {"rateLimits": {"primary": {"usedPercent": 5}}}

        line = format_codex_status_line(data, show_account=True)

        assert line == "🤖 Codex: 5h 5%"

    def test_account_display_env_is_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CCDB_CODEX_STATUS_ACCOUNT", raising=False)
        assert not _account_display_enabled()

        monkeypatch.setenv("CCDB_CODEX_STATUS_ACCOUNT", "yes")
        assert _account_display_enabled()

    def test_unlimited_credits(self) -> None:
        data = {"rateLimits": {"primary": {"usedPercent": 5}, "credits": {"unlimited": True}}}
        line = format_codex_status_line(data)
        assert line is not None
        assert "クレジット 無制限" in line

    def test_rounds_fractional_percent(self) -> None:
        data = {"rateLimits": {"primary": {"usedPercent": 12.6}}}
        line = format_codex_status_line(data)
        assert line is not None
        assert "5h 13%" in line

    def test_rate_limit_reached_warning(self) -> None:
        data = {
            "rateLimits": {
                "primary": {"usedPercent": 100},
                "rateLimitReachedType": "rate_limit_reached",
            }
        }
        line = format_codex_status_line(data)
        assert line is not None
        assert "上限到達" in line

    @pytest.mark.parametrize("bad", [None, {}, {"rateLimits": None}, {"rateLimits": {}}, "x"])
    def test_returns_none_for_unusable(self, bad: object) -> None:
        assert format_codex_status_line(bad) is None  # type: ignore[arg-type]


class TestProviderCache:
    async def test_caches_within_ttl(self) -> None:
        calls = {"n": 0}

        async def fake_fetch(_cmd: str) -> dict:
            calls["n"] += 1
            return SAMPLE

        now = {"t": 1000.0}
        prov = CodexStatusProvider("codex", ttl=90.0, fetcher=fake_fetch, clock=lambda: now["t"])

        first = await prov.get_line()
        assert first is not None
        # Second call within TTL → cached, no extra fetch.
        now["t"] = 1050.0
        await prov.get_line()
        assert calls["n"] == 1

        # After TTL expiry → refetch.
        now["t"] = 1200.0
        await prov.get_line()
        assert calls["n"] == 2

    async def test_failure_uses_short_ttl(self) -> None:
        calls = {"n": 0}

        async def failing_fetch(_cmd: str) -> None:
            calls["n"] += 1
            return None

        now = {"t": 0.0}
        prov = CodexStatusProvider(
            "codex", ttl=90.0, fail_ttl=30.0, fetcher=failing_fetch, clock=lambda: now["t"]
        )

        assert await prov.get_line() is None
        # Within fail_ttl → still cached (no refetch).
        now["t"] = 10.0
        assert await prov.get_line() is None
        assert calls["n"] == 1
        # After fail_ttl → refetch.
        now["t"] = 40.0
        assert await prov.get_line() is None
        assert calls["n"] == 2

    async def test_force_bypasses_cache(self) -> None:
        calls = {"n": 0}

        async def fake_fetch(_cmd: str) -> dict:
            calls["n"] += 1
            return SAMPLE

        prov = CodexStatusProvider("codex", fetcher=fake_fetch, clock=lambda: 0.0)
        await prov.get_line()
        await prov.get_line(force=True)
        assert calls["n"] == 2
