"""Tests for claude_discord.reminders — pure time parsing and prompt building."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from claude_discord.reminders import (
    DEFAULT_CHECK_INTERVAL_SECONDS,
    build_conditional_prompt,
    build_plain_reminder_text,
    parse_until,
    parse_when,
    repeat_interval_seconds,
)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 8, 7, 14, 0, 0, tzinfo=JST)


class TestParseWhen:
    def test_clock_time_later_today(self) -> None:
        assert parse_when("21:30", now=NOW) == datetime(2026, 8, 7, 21, 30, tzinfo=JST)

    def test_clock_time_already_passed_rolls_to_tomorrow(self) -> None:
        assert parse_when("09:00", now=NOW) == datetime(2026, 8, 8, 9, 0, tzinfo=JST)

    def test_clock_time_equal_to_now_rolls_to_tomorrow(self) -> None:
        """A reminder for "right now" is never useful — it means tomorrow."""
        assert parse_when("14:00", now=NOW) == datetime(2026, 8, 8, 14, 0, tzinfo=JST)

    def test_single_digit_hour(self) -> None:
        assert parse_when("9:05", now=NOW) == datetime(2026, 8, 8, 9, 5, tzinfo=JST)

    @pytest.mark.parametrize(
        ("raw", "expected_delta"),
        [
            ("30m", timedelta(minutes=30)),
            ("+30m", timedelta(minutes=30)),
            ("2h", timedelta(hours=2)),
            ("3d", timedelta(days=3)),
            ("90s", timedelta(seconds=90)),
        ],
    )
    def test_relative_offsets(self, raw: str, expected_delta: timedelta) -> None:
        assert parse_when(raw, now=NOW) == NOW + expected_delta

    def test_iso_datetime_with_offset(self) -> None:
        assert parse_when("2026-08-08T09:30:00+09:00", now=NOW) == datetime(
            2026, 8, 8, 9, 30, tzinfo=JST
        )

    def test_iso_datetime_without_offset_assumes_local(self) -> None:
        parsed = parse_when("2026-08-08T09:30", now=NOW)
        assert parsed.utcoffset() == NOW.utcoffset()
        assert (parsed.year, parsed.month, parsed.day, parsed.hour) == (2026, 8, 8, 9)

    @pytest.mark.parametrize("raw", ["", "   ", "tonight", "25:00", "12:60", "0m", "-2h", "abc"])
    def test_rejects_garbage(self, raw: str) -> None:
        with pytest.raises(ValueError):
            parse_when(raw, now=NOW)

    def test_rejects_past_iso_datetime(self) -> None:
        with pytest.raises(ValueError, match="past"):
            parse_when("2026-08-06T09:00:00+09:00", now=NOW)


class TestParseUntil:
    def test_date_expands_to_end_of_day(self) -> None:
        assert parse_until("2026-08-07", now=NOW) == datetime(2026, 8, 7, 23, 59, 59, tzinfo=JST)

    def test_datetime_is_kept(self) -> None:
        assert parse_until("2026-08-08T06:00:00+09:00", now=NOW) == datetime(
            2026, 8, 8, 6, 0, tzinfo=JST
        )

    def test_relative_offset(self) -> None:
        assert parse_until("2d", now=NOW) == NOW + timedelta(days=2)

    def test_none_means_no_expiry(self) -> None:
        assert parse_until(None, now=NOW) is None

    def test_rejects_expiry_in_the_past(self) -> None:
        with pytest.raises(ValueError, match="past"):
            parse_until("2026-08-06", now=NOW)


class TestRepeatIntervalSeconds:
    def test_once_uses_the_default_check_interval(self) -> None:
        """A one-shot still needs a nominal interval — the row requires one."""
        assert repeat_interval_seconds(None) == DEFAULT_CHECK_INTERVAL_SECONDS

    @pytest.mark.parametrize(
        ("every", "expected"),
        [("hourly", 3600), ("daily", 86400), ("weekly", 604800), ("30m", 1800), ("6h", 21600)],
    )
    def test_named_and_relative_intervals(self, every: str, expected: int) -> None:
        assert repeat_interval_seconds(every) == expected

    def test_rejects_garbage(self) -> None:
        with pytest.raises(ValueError):
            repeat_interval_seconds("sometimes")


class TestBuildConditionalPrompt:
    def _prompt(self, **kwargs: object) -> str:
        defaults = {
            "what": "IDR のアンケートを出す",
            "check": "Gmail の in:sent to:idr.co after:2026/08/07 が 1 件以上あるか",
            "task_name": "remind-idr-1234",
        }
        defaults.update(kwargs)
        return build_conditional_prompt(**defaults)  # type: ignore[arg-type]

    def test_includes_the_condition_and_the_reminder(self) -> None:
        prompt = self._prompt()
        assert "in:sent to:idr.co" in prompt
        assert "IDR のアンケートを出す" in prompt

    def test_tells_the_session_to_stay_silent_when_already_done(self) -> None:
        prompt = self._prompt()
        assert "silent" in prompt.lower()

    def test_carries_the_self_delete_instruction_with_the_task_name(self) -> None:
        """Without self-deletion a satisfied reminder would keep firing."""
        prompt = self._prompt()
        assert "remind-idr-1234" in prompt
        assert "/api/tasks" in prompt

    def test_verification_precedes_notification(self) -> None:
        """Order matters: check first, only then decide to speak."""
        prompt = self._prompt()
        assert prompt.index("Verify") < prompt.index("Remind")

    def test_rejects_empty_inputs(self) -> None:
        with pytest.raises(ValueError):
            self._prompt(what="  ")
        with pytest.raises(ValueError):
            self._prompt(check="")


class TestBuildPlainReminderText:
    def test_prefixes_with_a_clock_and_keeps_the_message(self) -> None:
        assert "買い物" in build_plain_reminder_text("買い物")

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            build_plain_reminder_text("   ")


class TestExtractReminderWhat:
    def test_round_trips_the_subject(self) -> None:
        from claude_discord.reminders import extract_reminder_what

        prompt = build_conditional_prompt(
            what="IDR のアンケートを出す", check="Gmail を見る", task_name="remind-1"
        )
        assert extract_reminder_what(prompt) == "IDR のアンケートを出す"

    def test_returns_none_for_an_unrelated_task_prompt(self) -> None:
        from claude_discord.reminders import extract_reminder_what

        assert extract_reminder_what("Check the CI build and report") is None

    def test_returns_none_for_empty_input(self) -> None:
        from claude_discord.reminders import extract_reminder_what

        assert extract_reminder_what("") is None
