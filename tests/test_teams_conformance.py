"""The shared contract, run against the Teams surface that actually ships.

This is the point of the whole abstraction: the same `check_surface` that keeps
Discord honest is now pointed at `TeamsSurface`, so "Teams is missing
something" becomes a CI failure rather than a discovery a user makes months
later.

Two things about *how* it is run are deliberate.

**The fake is the transport, not the surface.** The subclass below adds no
behaviour — only the two accessors the contract reads for evidence, derived
from a recording connector. Everything being checked is the shipped class's own
decision.

**The one thing Teams cannot do yet is pinned by name, not skipped.** A
conformance run that reported green while file contents went nowhere would be
exactly the kind of green this project keeps learning not to trust. The test
below asserts the *exact* set of failures, so closing the gap is what makes it
pass and nothing else does.
"""

from __future__ import annotations

from typing import Any

from claude_code_core.conformance import check_surface
from claude_teams.capabilities import TEAMS_CAPABILITIES
from claude_teams.conversation import ConversationRef
from claude_teams.pacer import UpdatePacer
from claude_teams.surface import TeamsSurface

REF = ConversationRef(
    service_url="https://smba.trafficmanager.net/emea/",
    conversation_id="19:conformance@thread.tacv2",
)

#: The check that Teams does not yet satisfy, and the reason. When file
#: delivery lands, this list becomes empty and the assertion below is what
#: says so.
KNOWN_GAPS = ["all files are delivered"]


class _RecordingConnector:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self._next = 0

    async def send_activity(self, ref: ConversationRef, body: dict[str, Any]) -> str:
        if "text" in body:
            self.texts.append(body["text"])
        self._next += 1
        return f"activity-{self._next}"

    async def update_activity(
        self, ref: ConversationRef, activity_id: str, body: dict[str, Any]
    ) -> None:
        return None


class ObservedTeamsSurface(TeamsSurface):
    """The shipped surface plus the contract's two evidence accessors.

    Adding these to the production class would put test scaffolding in every
    deployment. Deriving them from the recording transport keeps the behaviour
    under test entirely unmodified.
    """

    def __init__(self, connector: _RecordingConnector) -> None:
        super().__init__(
            thread_key=9_007_199_254_740_993,
            ref=REF,
            connector=connector,
            title="Conformance",
            # A real interval would make the contract's own checks sleep for
            # minutes. Pacing is proved in tests/test_teams_pacer.py.
            pacer=UpdatePacer(0.001),
        )
        self._recorder = connector

    @property
    def conformance_sent_text(self) -> list[str]:
        return self._recorder.texts

    @property
    def conformance_delivered_files(self) -> list[str]:
        # Teams cannot transfer file contents yet, and the surface does not
        # pretend otherwise. Claiming names here would turn the gap green.
        return []


_open: list[ObservedTeamsSurface] = []


async def _make_surface() -> ObservedTeamsSurface:
    surface = ObservedTeamsSurface(_RecordingConnector())
    _open.append(surface)
    return surface


async def _close_all() -> None:
    while _open:
        await _open.pop().close()


class TestTeamsSatisfiesTheContract:
    async def test_every_check_passes_except_the_pinned_gap(self) -> None:
        report = await check_surface(_make_surface)
        await _close_all()

        failed = [failure.split(":", 1)[0] for failure in report.failures]
        assert failed == KNOWN_GAPS, report.summary()

    async def test_the_contract_actually_exercised_the_surface(self) -> None:
        # A contract that ran zero checks would also report zero unexpected
        # failures. Pin the count so an import mistake cannot look like a pass.
        report = await check_surface(_make_surface)
        await _close_all()
        assert len(report.passed) >= 15


class TestCapabilitiesMatchBehaviour:
    async def test_the_surface_reports_the_shipped_teams_numbers(self) -> None:
        surface = await _make_surface()
        assert surface.capabilities is TEAMS_CAPABILITIES
        await _close_all()
