"""Normal-process wiring for the private half of the Teams relay."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_discord.teams_integration import (
    FrontendRouter,
    TeamsRuntime,
    TeamsSessionHost,
    parse_frontends,
)
from claude_teams.activity import parse_activity


def activity(
    text: str = "ship it",
    *,
    conversation_id: str = "19:thread@thread.tacv2;messageid=1",
    conversation_type: str = "channel",
    mentioned: bool = True,
    sender: str = "user-1",
) -> Any:
    entities = (
        [{"type": "mention", "mentioned": {"id": "bot-id"}, "text": "<at>Relay</at>"}]
        if mentioned
        else []
    )
    return parse_activity(
        {
            "type": "message",
            "id": "activity-1",
            "serviceUrl": "https://smba.trafficmanager.net/jp/",
            "conversation": {"id": conversation_id, "conversationType": conversation_type},
            "from": {"id": sender, "name": "User"},
            "recipient": {"id": "bot-id"},
            "text": f"<at>Relay</at> {text}" if mentioned else text,
            "entities": entities,
            "channelData": {"channel": {"id": "channel-1"}, "tenant": {"id": "tenant-1"}},
        }
    )


class TestFrontendSelection:
    def test_default_remains_discord_only(self) -> None:
        assert parse_frontends("") == ("discord",)

    def test_discord_and_teams_are_selected_in_order(self) -> None:
        assert parse_frontends(" discord, teams ") == ("discord", "teams")

    @pytest.mark.parametrize("value", ["teams,teams", "discord,email", ","])
    def test_invalid_selection_is_rejected(self, value: str) -> None:
        with pytest.raises(ValueError, match="CCDB_FRONTENDS"):
            parse_frontends(value)


class TestFrontendRouter:
    async def test_resolves_the_frontend_that_owns_the_key(self) -> None:
        discord = SimpleNamespace(
            name="discord", resolve_surface=AsyncMock(return_value=None), create_surface=AsyncMock()
        )
        teams_surface = object()
        teams = SimpleNamespace(
            name="teams",
            resolve_surface=AsyncMock(return_value=teams_surface),
            create_surface=AsyncMock(),
        )
        router = FrontendRouter(discord)
        router.add(teams)

        assert await router.resolve_surface(42) is teams_surface
        discord.resolve_surface.assert_awaited_once_with(42)
        teams.resolve_surface.assert_awaited_once_with(42)

    def test_duplicate_frontend_names_are_rejected(self) -> None:
        router = FrontendRouter(SimpleNamespace(name="discord"))
        with pytest.raises(ValueError, match="discord"):
            router.add(SimpleNamespace(name="discord"))


@dataclass
class Record:
    session_id: str
    backend: str | None = "claude"
    working_dir: str | None = "/work"


def make_host(*, record: Record | None = None) -> tuple[TeamsSessionHost, dict[str, Any]]:
    surface = SimpleNamespace(thread_key=42)
    frontend = SimpleNamespace(
        interactions=SimpleNamespace(resolve=MagicMock(return_value=True)),
        files=MagicMock(),
        remember=MagicMock(),
        resolve_surface=AsyncMock(return_value=surface),
    )
    ledger = SimpleNamespace(register=AsyncMock(return_value=42))
    repo = SimpleNamespace(get=AsyncMock(return_value=record))
    runner = SimpleNamespace(command="claude", working_dir="/work")
    factory = SimpleNamespace(build=MagicMock(return_value=runner), codex_command="codex")
    settings = SimpleNamespace(
        current_backend=AsyncMock(return_value="claude"),
        current_model=AsyncMock(return_value="sonnet"),
        current_effort=AsyncMock(return_value=None),
    )
    calls: list[Any] = []

    async def run_session(config: Any) -> str:
        calls.append(config)
        return "session-new"

    host = TeamsSessionHost(
        app_id="bot-id",
        frontend=frontend,
        ledger=ledger,
        session_repo=repo,
        backend_factory=factory,
        backend_settings=settings,
        run_session=run_session,
    )
    return host, {
        "surface": surface,
        "frontend": frontend,
        "ledger": ledger,
        "repo": repo,
        "factory": factory,
        "settings": settings,
        "runner": runner,
        "calls": calls,
    }


class TestTeamsSessionHost:
    async def test_new_channel_message_reaches_the_real_session_path(self) -> None:
        host, deps = make_host()

        await host.handle(activity("build the feature"))

        deps["ledger"].register.assert_awaited_once_with(
            "teams", "19:thread@thread.tacv2;messageid=1", parent_external_id="channel-1"
        )
        deps["frontend"].remember.assert_called_once_with(
            "19:thread@thread.tacv2;messageid=1", "https://smba.trafficmanager.net/jp/"
        )
        config = deps["calls"][0]
        assert config.surface is deps["surface"]
        assert config.prompt == "build the feature"
        assert config.session_id is None
        assert config.session_origin == "teams"
        deps["factory"].build.assert_called_once_with(
            backend="claude", model="sonnet", thread_id=42
        )

    async def test_existing_conversation_resumes_its_session(self) -> None:
        host, deps = make_host(record=Record("session-old"))

        await host.handle(activity(conversation_type="personal", mentioned=False))

        assert deps["calls"][0].session_id == "session-old"
        assert deps["calls"][0].runner.working_dir == "/work"

    async def test_channel_message_without_a_bot_mention_is_ignored(self) -> None:
        host, deps = make_host()
        await host.handle(activity(mentioned=False))
        assert deps["calls"] == []

    async def test_personal_message_needs_no_mention(self) -> None:
        host, deps = make_host()
        await host.handle(activity(conversation_type="personal", mentioned=False))
        assert len(deps["calls"]) == 1

    async def test_the_bot_does_not_answer_itself(self) -> None:
        host, deps = make_host()
        await host.handle(activity(sender="bot-id"))
        assert deps["calls"] == []

    async def test_an_invoke_resolves_the_shared_interaction_registry(self) -> None:
        host, deps = make_host()
        invoke = parse_activity(
            {
                "type": "invoke",
                "id": "invoke-1",
                "serviceUrl": "https://smba.trafficmanager.net/jp/",
                "conversation": {"id": "conversation-1", "conversationType": "personal"},
                "from": {"id": "user-1"},
                "recipient": {"id": "bot-id"},
                "name": "adaptiveCard/action",
                "value": {"action": {"data": {"ccdb_prompt": "prompt-1", "ccdb_value": "yes"}}},
            }
        )

        await host.handle(invoke)

        deps["frontend"].interactions.resolve.assert_called_once_with(
            "conversation-1", {"ccdb_prompt": "prompt-1", "ccdb_value": "yes"}
        )
        assert deps["calls"] == []


class TestTeamsRuntime:
    async def test_start_and_close_own_the_puller_and_http_session(self) -> None:
        puller = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
        session = SimpleNamespace(close=AsyncMock())
        runtime = TeamsRuntime(
            frontend=SimpleNamespace(name="teams"), puller=puller, session=session
        )

        await runtime.start()
        assert runtime.running is True
        puller.start.assert_awaited_once()

        await runtime.close()
        puller.close.assert_awaited_once()
        session.close.assert_awaited_once()
        assert runtime.running is False
