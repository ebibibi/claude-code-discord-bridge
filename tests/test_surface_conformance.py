"""The conformance contract, and proof that the vocabulary survives a third platform.

Two things are pinned here.

**The contract is satisfiable and it bites.** ``MemorySurface`` passes every
check; deliberately broken surfaces fail the specific check that should catch
them. A contract that only ever passes is decoration.

**Discord, Teams and Slack all fit in one capability vocabulary.** The
direction is Discord → Teams → Slack, and the cheapest possible moment to
discover that the vocabulary cannot express Slack is now, before a second
implementation is written against it. So Slack's real numbers are checked
against the model here even though no Slack frontend exists yet.

Capability figures below are from vendor documentation, cited inline. They are
test data, not configuration — the real presets live with each frontend, and
Teams' is now imported from :mod:`claude_teams.capabilities` rather than
restated here. A preset a test owns only proves the test is self-consistent.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from claude_code_core.conformance import check_surface
from claude_code_core.frontend import (
    ActivitySpec,
    Choice,
    ChoicePrompt,
    OutboundFile,
    SurfaceCapabilities,
)
from claude_code_core.memory_surface import MemorySurface
from claude_teams.capabilities import TEAMS_CAPABILITIES

# --- Capability presets under test -----------------------------------------
# Discord: 2,000 chars/message; bot reactions; no hourly edit budget.
DISCORD = SurfaceCapabilities(
    max_message_chars=2000,
    supports_reactions=True,
    supports_message_edit=True,
    supports_message_delete=True,
    supports_slash_commands=True,
    supports_pinned_dashboard=True,
    supports_thread_rename=True,
    live_update_budget_per_hour=1_000_000,
    stream_min_interval=1.5,
    max_files_per_message=10,
    monospace_width=55,
)
# Teams: the shipped preset, not a copy of it. If the frontend's own numbers
# ever stop satisfying the contract, that is the failure worth having.
TEAMS = TEAMS_CAPABILITIES
# Slack: 4,000 chars recommended per message; bots may add reactions;
# chat.postMessage is limited to ~1 message per second per channel with no
# hourly cap. https://docs.slack.dev/apis/web-api/rate-limits
SLACK = SurfaceCapabilities(
    max_message_chars=4000,
    supports_reactions=True,
    supports_message_edit=True,
    supports_message_delete=True,
    supports_slash_commands=True,
    supports_thread_rename=False,
    live_update_budget_per_hour=1_000_000,
    stream_min_interval=1.0,
    max_files_per_message=10,
    monospace_width=80,
)


class TestMemorySurfaceIsConformant:
    async def test_reference_implementation_passes_every_check(self) -> None:
        report = await check_surface(lambda: _make(DISCORD))
        assert report.ok, report.summary()

    @pytest.mark.parametrize("caps", [DISCORD, TEAMS, SLACK], ids=["discord", "teams", "slack"])
    async def test_conformance_holds_under_every_capability_set(
        self, caps: SurfaceCapabilities
    ) -> None:
        """The same implementation must stay correct when the numbers change.

        This is the check that would have caught a surface that only splits
        correctly at Discord's limit, or only delivers files correctly when
        ten fit in a message.
        """
        report = await check_surface(lambda: _make(caps))
        assert report.ok, report.summary()


class TestTheContractActuallyBites:
    """A contract that cannot fail is not a contract."""

    async def test_catches_a_surface_that_ignores_its_own_message_limit(self) -> None:
        class Oversharing(MemorySurface):
            async def send_text(self, text: str) -> str | None:
                self.conformance_sent_text.append(text)  # never splits
                return "msg-1"

        report = await check_surface(lambda: _make(DISCORD, cls=Oversharing))
        assert not report.ok
        assert any("long text is split to fit" in f for f in report.failures)

    async def test_catches_a_surface_that_drops_files_when_batching(self) -> None:
        class Forgetful(MemorySurface):
            async def deliver_files(self, files: Sequence[OutboundFile]) -> None:
                # A plausible bug: send only the first batch.
                cap = self.capabilities.max_files_per_message
                for f in list(files)[:cap]:
                    self.conformance_delivered_files.append(f.display_name)

        report = await check_surface(lambda: _make(TEAMS, cls=Forgetful))
        assert not report.ok
        assert any("all files are delivered" in f for f in report.failures)

    async def test_catches_a_surface_that_invents_an_answer(self) -> None:
        class Inventive(MemorySurface):
            async def prompt_choice(self, prompt: ChoicePrompt) -> tuple[str, ...] | None:
                return ("something-nobody-offered",)

        report = await check_surface(lambda: _make(DISCORD, cls=Inventive))
        assert not report.ok
        assert any("choice returns an offered value" in f for f in report.failures)

    async def test_catches_a_handle_that_is_not_idempotent(self) -> None:
        class Brittle(MemorySurface):
            async def open_activity(self, spec: ActivitySpec):  # type: ignore[override]
                handle = await super().open_activity(spec)

                async def complete(result, *, ok=True):
                    if handle.finished:
                        raise RuntimeError("already completed")
                    handle.finished = True

                handle.complete = complete  # type: ignore[method-assign]
                return handle

        report = await check_surface(lambda: _make(DISCORD, cls=Brittle))
        assert not report.ok
        assert any("activity lifecycle" in f for f in report.failures)

    async def test_report_summary_names_the_broken_check(self) -> None:
        class Nameless(MemorySurface):
            @property
            def external_id(self) -> str:
                return ""

        report = await check_surface(lambda: _make(DISCORD, cls=Nameless))
        assert "identity" in report.summary()


class TestVocabularySurvivesSlack:
    """Slack is the planned third frontend. Fixing the vocabulary after two
    implementations exist is far more expensive than checking it now."""

    def test_update_pacing_expresses_all_three_shapes(self) -> None:
        """Teams caps total operations per hour; Slack and Discord cap the
        rate. One expression covers both because the two limits are held
        separately and the stricter one wins.
        """
        # Teams: 1,800/hour dominates → 2s between updates.
        assert TEAMS.min_update_interval == pytest.approx(2.0)
        # Slack: no hourly cap, 1/sec per channel dominates.
        assert SLACK.min_update_interval == pytest.approx(1.0)
        # Discord: its own preferred streaming pace dominates.
        assert DISCORD.min_update_interval == pytest.approx(1.5)

    def test_each_platform_differs_from_the_others_somewhere(self) -> None:
        """If the three presets were identical the tests above would prove
        nothing, so assert they actually diverge."""
        assert TEAMS.supports_reactions != SLACK.supports_reactions
        assert DISCORD.max_message_chars != SLACK.max_message_chars != TEAMS.max_message_chars
        assert TEAMS.max_files_per_message != SLACK.max_files_per_message

    async def test_the_same_answer_renders_appropriately_on_each(self) -> None:
        long_answer = "\n\n".join(f"Point {i}. " + "detail " * 50 for i in range(30))
        counts = {}
        for name, caps in (("discord", DISCORD), ("teams", TEAMS), ("slack", SLACK)):
            surface = _make_sync(caps)
            await surface.send_text(long_answer)
            counts[name] = len(surface.conformance_sent_text)

        # Teams takes it whole; the narrower surfaces split, Discord most.
        assert counts["teams"] == 1
        assert counts["slack"] > 1
        assert counts["discord"] > counts["slack"]


class TestMemorySurfaceIsUsefulForAssertions:
    async def test_records_what_the_model_said(self) -> None:
        surface = _make_sync(DISCORD)
        await surface.send_text("the answer is 42")
        assert surface.conformance_sent_text == ["the answer is 42"]

    async def test_answers_are_served_in_order(self) -> None:
        surface = MemorySurface(DISCORD, answers=[["allow"], ["deny"]])
        prompt = ChoicePrompt(
            question="?",
            choices=(Choice(value="allow", label="A"), Choice(value="deny", label="D")),
        )
        assert await surface.prompt_choice(prompt) == ("allow",)
        assert await surface.prompt_choice(prompt) == ("deny",)
        assert await surface.prompt_choice(prompt) is None  # exhausted → unanswered

    async def test_stream_lands_in_the_transcript(self) -> None:
        surface = _make_sync(DISCORD)
        stream = surface.open_stream()
        await stream.append("par")
        await stream.append("tial")
        await stream.finalize()
        assert surface.conformance_sent_text == ["partial"]


# --- helpers ---------------------------------------------------------------


def _make_sync(
    caps: SurfaceCapabilities, cls: type[MemorySurface] = MemorySurface
) -> MemorySurface:
    return cls(caps, answers=[["allow"]], form_answers=[{"name": "Ebi", "note": "hi"}])


async def _make(
    caps: SurfaceCapabilities, cls: type[MemorySurface] = MemorySurface
) -> MemorySurface:
    return _make_sync(caps, cls)
