"""Tests for the Codex engine status footer helpers."""

from __future__ import annotations

import pytest

from claude_discord.discord_ui.engine_status import (
    CodexStatusProvider,
    format_codex_status_line,
)

# Representative `account/rateLimits/read` result (trimmed to what we read).
SAMPLE = {
    "rateLimits": {
        "limitId": "codex",
        "primary": {"usedPercent": 1, "windowDurationMins": 300, "resetsAt": 1782198285},
        "secondary": {"usedPercent": 8, "windowDurationMins": 10080, "resetsAt": 1782361421},
        "credits": {"hasCredits": False, "unlimited": False, "balance": "0"},
        "planType": "prolite",
        "rateLimitReachedType": None,
    }
}

# Team plans expose a SINGLE window as ``primary`` whose duration is a full
# week (10080 min) — there is no 5-hour window and ``secondary`` is null.
# Captured from a real ``codex app-server`` ``account/rateLimits/read`` call.
TEAM_SAMPLE = {
    "rateLimits": {
        "limitId": "codex",
        "primary": {"usedPercent": 33, "windowDurationMins": 10080, "resetsAt": 1785815516},
        "secondary": None,
        "credits": {"hasCredits": False, "unlimited": False, "balance": None},
        "planType": "team",
        "rateLimitReachedType": None,
    }
}


class TestFormat:
    def test_basic_line(self) -> None:
        line = format_codex_status_line(SAMPLE)
        assert line is not None
        assert "Codex" in line
        assert "5h 1%" in line
        assert "weekly 8%" in line
        assert "credits 0" in line
        assert "(prolite)" in line

    def test_team_plan_primary_is_weekly_not_5h(self) -> None:
        """Team plans have a weekly primary window — must not be labelled '5h'.

        Regression: the label was hardcoded to '5h' for ``primary``, so a team
        plan showed ``5h 33%`` for what is really a rolling 7-day quota. Users
        rightly expected a 5-hour reset that never came. The label must derive
        from ``windowDurationMins``.
        """
        line = format_codex_status_line(TEAM_SAMPLE)
        assert line is not None
        assert "5h" not in line
        assert "weekly 33%" in line
        assert "(team)" in line

    @pytest.mark.parametrize(
        ("mins", "expected_label"),
        [
            (300, "5h"),
            (10080, "weekly"),
            (1440, "1d"),
            (2880, "2d"),
        ],
    )
    def test_window_label_derived_from_duration(self, mins: int, expected_label: str) -> None:
        """The window label follows ``windowDurationMins``, not a fixed string."""
        data = {"rateLimits": {"primary": {"usedPercent": 10, "windowDurationMins": mins}}}
        line = format_codex_status_line(data)
        assert line is not None
        assert f"{expected_label} 10%" in line

    def test_unlimited_credits(self) -> None:
        data = {"rateLimits": {"primary": {"usedPercent": 5}, "credits": {"unlimited": True}}}
        line = format_codex_status_line(data)
        assert line is not None
        assert "credits unlimited" in line

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
        assert "limit reached" in line

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
