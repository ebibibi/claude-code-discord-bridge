"""``TeamsFrontend`` against the same contract ``DiscordFrontend`` passes.

The suite is the point: a scheduler resolving its follow-up conversation, a
webhook posting into one, and the REST API reaching one all go through this
object, and none of them know which platform is underneath. If Teams satisfies
the same five obligations, they work unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_core.conformance import check_frontend
from claude_code_core.frontend import issue_thread_key
from claude_teams.frontend import TeamsFrontend

SERVICE_URL = "https://smba.trafficmanager.net/emea/"
CHANNEL = "19:team-channel@thread.tacv2"


class FakeLedger:
    """The frontend_threads repository, in memory."""

    def __init__(self) -> None:
        self.rows: dict[int, Any] = {}
        self.by_external: dict[tuple[str, str], int] = {}

    async def register(
        self, frontend: str, external_id: str, *, parent_external_id: str | None = None
    ) -> int:
        existing = self.by_external.get((frontend, external_id))
        if existing is not None:
            return existing
        key = issue_thread_key(frontend, external_id, taken=set(self.rows))
        self.rows[key] = _Entry(key, frontend, external_id, parent_external_id)
        self.by_external[(frontend, external_id)] = key
        return key

    async def resolve(self, thread_key: int) -> Any:
        return self.rows.get(thread_key)


class _Entry:
    def __init__(
        self, thread_key: int, frontend: str, external_id: str, parent_external_id: str | None
    ) -> None:
        self.thread_key = thread_key
        self.frontend = frontend
        self.external_id = external_id
        self.parent_external_id = parent_external_id


class NullConnector:
    async def send_activity(self, ref: Any, body: Any) -> str:
        return "activity-1"

    async def update_activity(self, ref: Any, activity_id: str, body: Any) -> None:
        return None


class Creator:
    """Stands in for the Bot Connector's create-conversation call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._next = 0

    async def __call__(self, parent_id: str, title: str, service_url: str) -> str:
        self.calls.append((parent_id, title, service_url))
        self._next += 1
        return f"19:conv-{self._next}@thread.tacv2"


def build(**overrides: Any) -> TeamsFrontend:
    kwargs: dict[str, Any] = {
        "connector": NullConnector(),
        "ledger": FakeLedger(),
        "create_conversation": Creator(),
        "default_service_url": SERVICE_URL,
    }
    kwargs.update(overrides)
    connector = kwargs.pop("connector")
    ledger = kwargs.pop("ledger")
    return TeamsFrontend(connector, ledger, **kwargs)


class TestTheSharedContract:
    async def test_teams_passes_check_frontend(self) -> None:
        async def make() -> TeamsFrontend:
            return build()

        report = await check_frontend(make, parent_id=CHANNEL)
        assert report.ok, report.summary()

    async def test_the_contract_actually_ran(self) -> None:
        async def make() -> TeamsFrontend:
            return build()

        report = await check_frontend(make, parent_id=CHANNEL)
        assert len(report.passed) >= 5


class TestKeysAndTheLedger:
    async def test_a_created_conversation_is_recorded_with_its_parent(self) -> None:
        # Without the parent, a deployment can reopen a conversation but not
        # open a sibling beside it.
        ledger = FakeLedger()
        frontend = build(ledger=ledger)
        surface = await frontend.create_surface(parent_id=CHANNEL, title="Fix the parser")

        entry = ledger.rows[surface.thread_key]
        assert entry.frontend == "teams"
        assert entry.parent_external_id == CHANNEL

    async def test_the_key_is_a_surrogate_not_the_string(self) -> None:
        # Teams conversation ids are strings; every table in ccdb keys on an
        # integer. This is the whole reason issue_thread_key exists.
        frontend = build()
        surface = await frontend.create_surface(parent_id=CHANNEL, title="t")
        assert isinstance(surface.thread_key, int)
        assert surface.thread_key > 2**53, "a surrogate must not collide with a Discord snowflake"

    async def test_a_key_from_another_frontend_does_not_resolve(self) -> None:
        # One ledger holds every frontend's conversations. Handing back a Teams
        # surface for a Discord key would post a session's output into the
        # wrong platform entirely.
        ledger = FakeLedger()
        discord_key = await ledger.register("discord", "1535820929958027334")
        frontend = build(ledger=ledger)
        assert await frontend.resolve_surface(discord_key) is None


class TestServiceUrl:
    async def test_a_conversation_heard_from_can_be_posted_to_without_a_default(self) -> None:
        ledger = FakeLedger()
        frontend = build(ledger=ledger, default_service_url=None)
        key = await ledger.register("teams", "19:known@thread.tacv2")

        assert await frontend.resolve_surface(key) is None, "nothing known yet"
        frontend.remember("19:known@thread.tacv2", SERVICE_URL)
        resolved = await frontend.resolve_surface(key)
        assert resolved is not None and resolved.ref.service_url == SERVICE_URL

    async def test_an_unaddressable_conversation_is_none_not_an_invented_host(self) -> None:
        # Posting to a guessed host sends a session's output somewhere nobody
        # is reading, which is worse than not posting.
        ledger = FakeLedger()
        frontend = build(ledger=ledger, default_service_url=None)
        key = await ledger.register("teams", "19:cold@thread.tacv2")
        assert await frontend.resolve_surface(key) is None

    async def test_creating_without_a_host_raises_rather_than_guessing(self) -> None:
        # Loud here on purpose: this is a configuration error, not a fact of
        # life like a deleted thread.
        frontend = build(default_service_url=None)
        with pytest.raises(LookupError, match="serviceUrl"):
            await frontend.create_surface(parent_id=CHANNEL, title="t")


class TestScope:
    async def test_a_channel_conversation_is_treated_as_a_channel(self) -> None:
        frontend = build()
        surface = await frontend.create_surface(parent_id=CHANNEL, title="t")
        assert surface.ref.is_personal is False

    async def test_a_personal_conversation_is_recognised(self) -> None:
        ledger = FakeLedger()
        frontend = build(ledger=ledger)
        key = await ledger.register("teams", "a:1nHRUvIt9RaZfP")
        resolved = await frontend.resolve_surface(key)
        assert resolved is not None and resolved.ref.is_personal is True

    async def test_an_unrecognised_shape_is_treated_as_a_channel(self) -> None:
        # Wrong in the safe direction: a channel offers no file rather than
        # offering one that cannot be accepted.
        ledger = FakeLedger()
        frontend = build(ledger=ledger)
        key = await ledger.register("teams", "something-new@thread.unknown")
        resolved = await frontend.resolve_surface(key)
        assert resolved is not None and resolved.ref.is_personal is False


class TestCreationFailures:
    async def test_a_frontend_that_cannot_create_says_so(self) -> None:
        frontend = build(create_conversation=None)
        with pytest.raises(LookupError, match="create_conversation"):
            await frontend.create_surface(parent_id=CHANNEL, title="t")

    async def test_a_creation_that_returns_nothing_raises(self) -> None:
        async def creator(parent_id: str, title: str, service_url: str) -> str:
            return ""

        frontend = build(create_conversation=creator)
        with pytest.raises(LookupError, match="conversation id"):
            await frontend.create_surface(parent_id=CHANNEL, title="t")


class TestSharedRegistries:
    async def test_every_surface_shares_one_prompt_registry(self) -> None:
        # The endpoint routes an inbound press to a single registry. Surfaces
        # with registries of their own would each be unanswerable from it.
        frontend = build()
        first = await frontend.create_surface(parent_id=CHANNEL, title="one")
        second = await frontend.create_surface(parent_id=CHANNEL, title="two")
        assert first.interactions is second.interactions is frontend.interactions
        assert first.files is second.files is frontend.files


class TestLifecycle:
    async def test_start_and_close_are_no_ops(self) -> None:
        # The transport is inbound HTTP, not a socket to hold open.
        frontend = build()
        await frontend.start()
        await frontend.close()


class TestTheStockCreator:
    async def test_the_connector_starts_a_reply_chain_in_the_channel(self) -> None:
        # The id Teams returns already encodes the root message, which is what
        # keeps Thread=Session intact on a platform whose threads are a
        # property of a message rather than objects of their own.
        from claude_teams.connector import BotConnector

        posted: list[tuple[str, dict]] = []

        async def post_json(url: str, payload: dict, headers: dict) -> dict:
            posted.append((url, payload))
            return {"id": "19:new@thread.tacv2;messageid=1", "activityId": "1"}

        class Tokens:
            async def token(self) -> str:
                return "t"

        connector = BotConnector(Tokens(), post_json)
        conversation_id = await connector.create_conversation(SERVICE_URL, CHANNEL, "Fix it")

        assert conversation_id == "19:new@thread.tacv2;messageid=1"
        url, payload = posted[0]
        assert url.endswith("/v3/conversations")
        assert payload["channelData"]["channel"]["id"] == CHANNEL
        assert payload["activity"]["text"] == "Fix it"
