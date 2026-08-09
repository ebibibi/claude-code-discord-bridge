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

**The contract is run twice, because Teams is not one surface.** A personal
chat can transfer files through a consent card; a channel cannot, and saying
"Teams passes" without saying which Teams would hide that. So the personal run
must pass every check, and the channel run must fail *exactly* the file check —
an assertion that breaks in both directions, so the gap cannot quietly widen or
quietly close without the test saying so.
"""

from __future__ import annotations

from typing import Any

from claude_code_core.conformance import check_surface
from claude_teams.capabilities import TEAMS_CAPABILITIES
from claude_teams.conversation import ConversationRef
from claude_teams.pacer import UpdatePacer
from claude_teams.surface import TeamsSurface

SERVICE_URL = "https://smba.trafficmanager.net/emea/"
PERSONAL = ConversationRef(
    service_url=SERVICE_URL,
    conversation_id="19:conformance@thread.tacv2",
    conversation_type="personal",
)
CHANNEL = ConversationRef(
    service_url=SERVICE_URL,
    conversation_id="19:conformance-channel@thread.tacv2",
    conversation_type="channel",
)

#: What a channel still cannot do. Consent cards are personal-scope only, and
#: writing into a channel's folder is a Graph permission this deployment does
#: not hold.
CHANNEL_GAPS = ["all files are delivered"]


class _RecordingConnector:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.offered_files: list[str] = []
        self._next = 0

    async def send_activity(self, ref: ConversationRef, body: dict[str, Any]) -> str:
        if "text" in body:
            self.texts.append(body["text"])
        for attachment in body.get("attachments", []):
            if attachment.get("contentType", "").endswith("file.consent"):
                self.offered_files.append(attachment["name"])
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

    def __init__(self, connector: _RecordingConnector, ref: ConversationRef) -> None:
        super().__init__(
            thread_key=9_007_199_254_740_993,
            ref=ref,
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
        """Files this surface actually handed over to Teams.

        A consent card is where delivery stops being ccdb's move: the bytes
        transfer when the user accepts, and no unattended surface can do more
        than offer. A channel offers nothing, which is why its run fails this
        check rather than reporting a delivery that did not happen.
        """
        return self._recorder.offered_files


_open: list[ObservedTeamsSurface] = []


def _factory(ref: ConversationRef) -> Any:
    async def make() -> ObservedTeamsSurface:
        surface = ObservedTeamsSurface(_RecordingConnector(), ref)
        _open.append(surface)
        return surface

    return make


async def _close_all() -> None:
    while _open:
        await _open.pop().close()


class TestAPersonalChatSatisfiesTheWholeContract:
    async def test_nothing_fails(self) -> None:
        report = await check_surface(_factory(PERSONAL))
        await _close_all()
        assert report.ok, report.summary()

    async def test_the_contract_actually_exercised_the_surface(self) -> None:
        # A contract that ran zero checks would also report zero failures.
        # Pin the count so an import mistake cannot look like a pass.
        report = await check_surface(_factory(PERSONAL))
        await _close_all()
        assert len(report.passed) >= 18


class TestAChannelFailsExactlyOneCheck:
    async def test_only_file_delivery_is_missing(self) -> None:
        # Breaks in both directions: a new gap fails here, and so does closing
        # this one without updating the list.
        report = await check_surface(_factory(CHANNEL))
        await _close_all()

        failed = [failure.split(":", 1)[0] for failure in report.failures]
        assert failed == CHANNEL_GAPS, report.summary()


class TestCapabilitiesMatchBehaviour:
    async def test_the_surface_reports_the_shipped_teams_numbers(self) -> None:
        surface = await _factory(PERSONAL)()
        assert surface.capabilities is TEAMS_CAPABILITIES
        await _close_all()
