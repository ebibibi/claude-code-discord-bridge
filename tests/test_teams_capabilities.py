"""The Teams numbers, pinned where a wrong one would be expensive.

These are not tautologies. Each assertion here is a value that, if it drifted,
would break something the frontend cannot detect at runtime: a rate limit that
kills a conversation partway through a long session, or a claimed capability
that makes a caller skip the fallback it actually needs.
"""

from __future__ import annotations

from claude_teams.capabilities import TEAMS_CAPABILITIES as TEAMS


class TestRateLimits:
    def test_the_hourly_budget_governs_the_streaming_pace(self) -> None:
        # This is the whole reason the two knobs are separate. Teams' preferred
        # pace is 1s, but 1,800 operations per hour only allows one every 2s,
        # and the stricter of the two has to win — otherwise a long session
        # exhausts its budget and stops updating with no error anywhere.
        assert TEAMS.stream_min_interval == 1.0
        assert TEAMS.live_update_budget_per_hour == 1800
        assert TEAMS.min_update_interval == 2.0

    def test_teams_is_slower_than_discord_despite_preferring_a_faster_pace(self) -> None:
        from claude_discord.discord_ui.chunker import DISCORD_CAPABILITIES

        assert TEAMS.stream_min_interval < DISCORD_CAPABILITIES.stream_min_interval
        assert TEAMS.min_update_interval > DISCORD_CAPABILITIES.min_update_interval


class TestAffordancesTeamsLacks:
    def test_a_bot_cannot_react(self) -> None:
        # Discord's status dots ride on reactions. Teams has no bot reaction
        # API at all, so a caller that assumes one silently loses every status
        # signal rather than failing.
        assert TEAMS.supports_reactions is False

    def test_there_are_no_slash_commands(self) -> None:
        # The manifest's commandLists looks like slash commands and is not: it
        # only pre-fills message text. The text-command router is mandatory.
        assert TEAMS.supports_slash_commands is False

    def test_files_are_delivered_as_links(self) -> None:
        assert TEAMS.file_delivery == "link"
        assert TEAMS.max_files_per_message == 1


class TestUnimplementedRenderingIsNotClaimed:
    def test_rendering_capabilities_are_still_off(self) -> None:
        # Teams can render these; this surface does not emit the markup for
        # them yet. Claiming them early is how a frontend ends up shipping
        # broken output that no test can see.
        assert TEAMS.supports_tables is False
        assert TEAMS.supports_headings is False
        assert TEAMS.supports_inline_images is False


class TestMessageSize:
    def test_one_answer_fits_in_one_message(self) -> None:
        from claude_discord.discord_ui.chunker import DISCORD_CAPABILITIES

        assert TEAMS.max_message_chars == 80_000
        assert TEAMS.max_message_chars > DISCORD_CAPABILITIES.max_message_chars * 20
