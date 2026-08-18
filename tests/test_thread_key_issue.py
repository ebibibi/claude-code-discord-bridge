"""Issuing a ThreadKey must never hand two conversations the same integer.

The key is the primary key of the sessions table. Two conversations sharing one
means the second session silently overwrites the first — no error, no log, just
a thread whose history belongs to somebody else. Discord cannot hit this
(snowflakes are already unique), which is exactly why it needs a test: the case
only appears once a frontend has to mint surrogates.
"""

from __future__ import annotations

import pytest

from claude_code_core.frontend import derive_thread_key, issue_thread_key


class TestDiscord:
    def test_a_snowflake_is_used_verbatim(self) -> None:
        assert (
            issue_thread_key("discord", "1535820929958027334", taken=set()) == 1535820929958027334
        )

    def test_a_non_numeric_discord_id_is_rejected(self) -> None:
        """Silently hashing it would produce a key no Discord call could use."""
        with pytest.raises(ValueError):
            issue_thread_key("discord", "not-a-snowflake", taken=set())


class TestSurrogates:
    def test_the_same_conversation_always_gets_the_same_key(self) -> None:
        first = issue_thread_key("teams", "19:abc@thread.tacv2", taken=set())
        second = issue_thread_key("teams", "19:abc@thread.tacv2", taken=set())

        assert first == second == derive_thread_key("teams", "19:abc@thread.tacv2")

    def test_a_surrogate_can_never_look_like_a_snowflake(self) -> None:
        key = issue_thread_key("teams", "19:abc@thread.tacv2", taken=set())

        assert key > 2**53
        assert key < 2**63

    def test_two_frontends_with_the_same_id_get_different_keys(self) -> None:
        a = issue_thread_key("teams", "conversation-1", taken=set())
        b = issue_thread_key("slack", "conversation-1", taken=set())

        assert a != b

    def test_a_taken_key_is_probed_past_rather_than_reused(self) -> None:
        """A hash collision must cost a different key, not a shared one."""
        natural = derive_thread_key("teams", "19:abc@thread.tacv2")

        key = issue_thread_key("teams", "19:abc@thread.tacv2", taken={natural})

        assert key != natural
        assert key > 2**53

    def test_probing_stays_deterministic(self) -> None:
        natural = derive_thread_key("teams", "19:abc@thread.tacv2")
        taken = {natural}

        assert issue_thread_key("teams", "19:abc@thread.tacv2", taken=taken) == issue_thread_key(
            "teams", "19:abc@thread.tacv2", taken=taken
        )

    def test_a_crowded_neighbourhood_still_yields_a_free_key(self) -> None:
        external = "19:abc@thread.tacv2"
        taken = {derive_thread_key("teams", external)}
        for _ in range(40):
            taken.add(issue_thread_key("teams", external, taken=taken))

        assert len(taken) == 41

    def test_an_exhausted_probe_budget_raises_rather_than_reusing(self) -> None:
        """The one thing it must never do is hand back a key already in use."""

        class Everything:
            def __contains__(self, _: object) -> bool:
                return True

        with pytest.raises(ValueError, match="free thread key"):
            issue_thread_key("teams", "19:abc@thread.tacv2", taken=Everything())

    def test_an_empty_external_id_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            issue_thread_key("teams", "", taken=set())
