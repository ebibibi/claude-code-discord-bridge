"""Tests for the frontend-agnostic conversation surface protocol.

This module has no implementations yet — it defines the vocabulary that both
``claude_discord`` and (later) ``claude_teams`` speak. The tests pin the
invariants that make the vocabulary safe to implement against:

* value objects reject malformed input at construction (fail fast at the boundary)
* ``SurfaceCapabilities`` defaults are *conservative*, so a frontend that
  forgets to declare a capability is treated as not having it
* ``derive_thread_key`` is deterministic, collision-scoped per frontend, and
  fits SQLite's signed 64-bit INTEGER
"""

from __future__ import annotations

import dataclasses

import pytest

from claude_code_core.frontend import (
    ActivitySpec,
    Choice,
    ChoicePrompt,
    FormField,
    FormPrompt,
    InboundMessage,
    Mention,
    Notice,
    NoticeLevel,
    OutboundFile,
    StatusKind,
    SurfaceCapabilities,
    derive_thread_key,
)

# ---------------------------------------------------------------------------
# derive_thread_key
# ---------------------------------------------------------------------------


class TestDeriveThreadKey:
    def test_is_deterministic(self) -> None:
        cid = "19:aebd0ad4d6ab42c8b9ed19c251c2fc37@thread.tacv2;messageid=1481567603816"
        assert derive_thread_key("teams", cid) == derive_thread_key("teams", cid)

    def test_scoped_by_frontend(self) -> None:
        """The same external id on two frontends must not collide."""
        assert derive_thread_key("teams", "abc") != derive_thread_key("discord", "abc")

    def test_distinct_ids_differ(self) -> None:
        keys = {derive_thread_key("teams", f"19:conv{i}@thread.tacv2") for i in range(1000)}
        assert len(keys) == 1000

    def test_fits_signed_64bit_and_is_positive(self) -> None:
        """SQLite INTEGER is signed 64-bit; a negative or oversized key corrupts the PK."""
        for i in range(500):
            key = derive_thread_key("teams", f"conversation-{i}")
            assert 0 < key <= 2**63 - 1

    def test_does_not_collide_with_discord_snowflakes(self) -> None:
        """Discord thread ids are used verbatim as thread keys, so derived keys
        must live above the snowflake range to stay unambiguous forever.

        Snowflakes are 63-bit values whose high bits encode a millisecond
        timestamp since 2015. Even in year 2100 they stay below 2**53, so
        deriving into the top half of the range keeps the two spaces disjoint.
        """
        for i in range(500):
            assert derive_thread_key("teams", f"c{i}") > 2**53

    def test_rejects_empty_inputs(self) -> None:
        with pytest.raises(ValueError):
            derive_thread_key("", "abc")
        with pytest.raises(ValueError):
            derive_thread_key("teams", "")


# ---------------------------------------------------------------------------
# SurfaceCapabilities
# ---------------------------------------------------------------------------


class TestSurfaceCapabilities:
    def test_defaults_are_conservative(self) -> None:
        """A frontend that declares nothing must be assumed to support nothing.

        This is what makes adding a capability field a non-breaking change: a
        third-party frontend that has not been updated keeps rendering the
        plain-text fallback instead of silently claiming a feature it lacks.
        """
        caps = SurfaceCapabilities(max_message_chars=2000)
        assert caps.supports_tables is False
        assert caps.supports_headings is False
        assert caps.supports_inline_images is False
        assert caps.supports_reactions is False
        assert caps.supports_message_edit is False
        assert caps.supports_message_delete is False
        assert caps.supports_slash_commands is False
        assert caps.supports_pinned_dashboard is False
        assert caps.max_files_per_message == 1
        assert caps.file_delivery == "inline"

    def test_is_frozen(self) -> None:
        caps = SurfaceCapabilities(max_message_chars=2000)
        with pytest.raises(dataclasses.FrozenInstanceError):
            caps.supports_reactions = True  # type: ignore[misc]

    def test_rejects_nonpositive_message_limit(self) -> None:
        with pytest.raises(ValueError):
            SurfaceCapabilities(max_message_chars=0)

    def test_rejects_nonpositive_update_budget(self) -> None:
        with pytest.raises(ValueError):
            SurfaceCapabilities(max_message_chars=2000, live_update_budget_per_hour=0)

    def test_update_interval_floor_derives_from_budget(self) -> None:
        """Teams allows 1,800 updates/hour per conversation → 2 s between edits.

        Callers should ask the capability rather than hardcoding a sleep, so a
        frontend with a tighter budget slows them down automatically.
        """
        teams = SurfaceCapabilities(max_message_chars=80_000, live_update_budget_per_hour=1800)
        assert teams.min_update_interval == pytest.approx(2.0)

    def test_generous_budget_falls_back_to_declared_interval(self) -> None:
        discord = SurfaceCapabilities(
            max_message_chars=2000,
            live_update_budget_per_hour=1_000_000,
            stream_min_interval=1.5,
        )
        assert discord.min_update_interval == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class TestOutboundFile:
    def test_accepts_path_only(self) -> None:
        f = OutboundFile(display_name="a.md", path="/tmp/a.md")
        assert f.path == "/tmp/a.md"

    def test_accepts_blob_only(self) -> None:
        f = OutboundFile(display_name="a.md", blob=b"hello")
        assert f.blob == b"hello"

    def test_rejects_neither(self) -> None:
        with pytest.raises(ValueError):
            OutboundFile(display_name="a.md")

    def test_rejects_both(self) -> None:
        with pytest.raises(ValueError):
            OutboundFile(display_name="a.md", path="/tmp/a.md", blob=b"x")

    def test_rejects_empty_display_name(self) -> None:
        with pytest.raises(ValueError):
            OutboundFile(display_name="", path="/tmp/a.md")

    def test_display_name_is_reduced_to_basename(self) -> None:
        """A caller-supplied path must never embed directory components in the
        name shown to (or uploaded on behalf of) the user."""
        f = OutboundFile(display_name="../../etc/passwd", path="/tmp/a")
        assert f.display_name == "passwd"


class TestChoicePrompt:
    def test_rejects_no_way_to_answer(self) -> None:
        with pytest.raises(ValueError):
            ChoicePrompt(question="?")

    def test_free_text_only_is_valid(self) -> None:
        p = ChoicePrompt(question="?", allow_free_text=True)
        assert p.choices == ()

    def test_rejects_duplicate_choice_values(self) -> None:
        with pytest.raises(ValueError):
            ChoicePrompt(
                question="?",
                choices=(Choice(value="a", label="A"), Choice(value="a", label="A again")),
            )

    def test_default_on_timeout_must_be_a_real_choice(self) -> None:
        with pytest.raises(ValueError):
            ChoicePrompt(
                question="?",
                choices=(Choice(value="allow", label="Allow"),),
                default_on_timeout="deny",
            )

    def test_valid_default_on_timeout(self) -> None:
        p = ChoicePrompt(
            question="Run this command?",
            choices=(Choice(value="allow", label="Allow"), Choice(value="deny", label="Deny")),
            default_on_timeout="deny",
            timeout_seconds=120,
        )
        assert p.default_on_timeout == "deny"


class TestFormPrompt:
    def test_rejects_empty_fields(self) -> None:
        with pytest.raises(ValueError):
            FormPrompt(title="t", fields=())

    def test_rejects_duplicate_field_keys(self) -> None:
        with pytest.raises(ValueError):
            FormPrompt(
                title="t",
                fields=(
                    FormField(key="name", label="Name", kind="text"),
                    FormField(key="name", label="Name 2", kind="text"),
                ),
            )

    def test_choice_field_requires_choices(self) -> None:
        with pytest.raises(ValueError):
            FormField(key="k", label="L", kind="choice")


class TestNotice:
    def test_requires_some_content(self) -> None:
        with pytest.raises(ValueError):
            Notice(level=NoticeLevel.INFO)

    def test_fields_only_is_valid(self) -> None:
        n = Notice(level=NoticeLevel.SUCCESS, fields=(("cost", "$0.01"),))
        assert n.fields == (("cost", "$0.01"),)

    def test_is_frozen(self) -> None:
        n = Notice(level=NoticeLevel.INFO, body="hi")
        with pytest.raises(dataclasses.FrozenInstanceError):
            n.body = "bye"  # type: ignore[misc]


class TestActivitySpec:
    def test_requires_title(self) -> None:
        with pytest.raises(ValueError):
            ActivitySpec(kind="tool", title="")


class TestInboundMessage:
    def test_text_defaults_to_raw_text(self) -> None:
        msg = InboundMessage(
            surface=None,  # type: ignore[arg-type]
            author_external_id="29:abc",
            author_display="Ebi",
            raw_text="hello",
        )
        assert msg.text == "hello"

    def test_mention_stripped_text_is_kept_separate(self) -> None:
        msg = InboundMessage(
            surface=None,  # type: ignore[arg-type]
            author_external_id="29:abc",
            author_display="Ebi",
            raw_text="<at>ccdb</at> summarize this",
            text="summarize this",
            is_mention=True,
        )
        assert msg.raw_text != msg.text
        assert msg.is_mention is True


class TestStatusKind:
    def test_every_tool_category_maps_to_a_status(self) -> None:
        """A new ToolCategory must not silently fall through to no status."""
        from claude_code_core.types import ToolCategory

        for category in ToolCategory:
            assert StatusKind.for_tool(category) is not None


class TestMention:
    def test_requires_external_user_id(self) -> None:
        with pytest.raises(ValueError):
            Mention(external_user_id="")
