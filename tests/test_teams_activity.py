"""Parsing an activity, minting an outbound token, and addressing a reply."""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_core.frontend import derive_thread_key
from claude_teams.activity import parse_activity
from claude_teams.connector import BotConnector
from claude_teams.token import OutboundTokenProvider

APP_ID = "11111111-2222-3333-4444-555555555555"
TENANT = "99999999-8888-7777-6666-555555555555"
SERVICE_URL = "https://smba.trafficmanager.net/emea/"
CONVERSATION = "19:abc@thread.tacv2;messageid=1481567603816"


def body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "message",
        "id": "1481567603816",
        "serviceUrl": SERVICE_URL,
        "conversation": {"id": CONVERSATION},
        "from": {"id": "29:user", "name": "Ada"},
        "recipient": {"id": f"28:{APP_ID}"},
        "text": "hello",
        "channelData": {
            "tenant": {"id": TENANT},
            "team": {"id": "19:team@thread.tacv2"},
            "channel": {"id": "19:channel@thread.tacv2"},
        },
    }
    payload.update(overrides)
    return payload


class TestParsing:
    def test_the_fields_a_reply_needs_are_extracted(self) -> None:
        activity = parse_activity(body())
        assert activity.conversation_id == CONVERSATION
        assert activity.service_url == SERVICE_URL
        assert activity.from_name == "Ada"
        assert activity.team_id == "19:team@thread.tacv2"

    def test_a_missing_conversation_id_is_named(self) -> None:
        payload = body()
        del payload["conversation"]
        with pytest.raises(ValueError, match="conversation.id"):
            parse_activity(payload)

    def test_a_missing_service_url_is_named(self) -> None:
        payload = body()
        del payload["serviceUrl"]
        with pytest.raises(ValueError, match="serviceUrl"):
            parse_activity(payload)

    def test_an_activity_with_no_text_is_still_an_activity(self) -> None:
        # A card action arrives as a message with no text at all.
        assert parse_activity(body(text=None)).text == ""

    def test_a_non_object_body_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="JSON object"):
            parse_activity(["not", "an", "activity"])

    def test_the_conversation_id_is_a_usable_thread_key(self) -> None:
        # The whole reason ThreadKey was made derivable: this string is what
        # Teams gives us, and ccdb's ledger keys on integers.
        activity = parse_activity(body())
        key = derive_thread_key("teams", activity.conversation_id)
        assert key == derive_thread_key("teams", activity.conversation_id)
        assert key > 0


class TestSelfRecognition:
    def test_the_bot_recognises_its_own_message(self) -> None:
        assert parse_activity(body(**{"from": {"id": APP_ID}})).is_from(APP_ID)

    def test_an_empty_app_id_never_matches(self) -> None:
        # Otherwise a misconfigured deployment would treat every anonymous
        # sender as itself and answer nobody.
        assert parse_activity(body(**{"from": {}})).is_from("") is False


class TestOutboundToken:
    async def test_the_token_is_fetched_once_and_reused(self) -> None:
        calls: list[dict[str, str]] = []

        async def post_form(_url: str, data: dict[str, str]) -> dict[str, Any]:
            calls.append(data)
            return {"access_token": "t-1", "expires_in": 3600}

        provider = OutboundTokenProvider(TENANT, APP_ID, "secret", post_form)
        assert await provider.token() == "t-1"
        assert await provider.token() == "t-1"
        assert len(calls) == 1

    async def test_it_refreshes_before_the_token_actually_expires(self) -> None:
        # Expiring mid-stream produces a 401 on one message in the middle of an
        # answer, which reads as the bot losing its place.
        now = [0.0]
        issued: list[str] = []

        async def post_form(_url: str, _data: dict[str, str]) -> dict[str, Any]:
            issued.append(f"t-{len(issued)}")
            return {"access_token": issued[-1], "expires_in": 3600}

        provider = OutboundTokenProvider(
            TENANT, APP_ID, "secret", post_form, refresh_margin=300.0, now=lambda: now[0]
        )
        assert await provider.token() == "t-0"
        now[0] = 3400  # still valid upstream, inside our margin
        assert await provider.token() == "t-1"

    async def test_a_response_without_a_token_does_not_leak_the_body(self) -> None:
        # Error bodies from the token endpoint can echo the request, secret
        # included, straight into a log line.
        async def post_form(_url: str, _data: dict[str, str]) -> dict[str, Any]:
            return {"error": "invalid_client", "error_description": "secret=hunter2"}

        provider = OutboundTokenProvider(TENANT, APP_ID, "hunter2", post_form)
        with pytest.raises(RuntimeError) as exc:
            await provider.token()
        assert "hunter2" not in str(exc.value)

    def test_the_token_url_is_tenant_scoped(self) -> None:
        async def post_form(_url: str, _data: dict[str, str]) -> dict[str, Any]:
            return {}

        provider = OutboundTokenProvider(TENANT, APP_ID, "secret", post_form)
        assert TENANT in provider.token_url


class StubTokens:
    async def token(self) -> str:
        return "t-1"


class TestConnector:
    async def test_a_reply_is_addressed_to_the_inbound_conversation(self) -> None:
        posted: list[tuple[str, dict[str, Any], dict[str, str]]] = []

        async def post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> None:
            posted.append((url, payload, headers))

        connector = BotConnector(StubTokens(), post_json)
        await connector.send_text(parse_activity(body()), "pong")

        url, payload, headers = posted[0]
        assert url.startswith(SERVICE_URL.rstrip("/") + "/v3/conversations/")
        assert CONVERSATION in url
        assert payload["text"] == "pong"
        assert headers["Authorization"] == "Bearer t-1"

    async def test_the_service_url_is_not_doubled_up_on_slashes(self) -> None:
        posted: list[str] = []

        async def post_json(url: str, _payload: dict[str, Any], _headers: dict[str, str]) -> None:
            posted.append(url)

        connector = BotConnector(StubTokens(), post_json)
        await connector.send_text(parse_activity(body(serviceUrl=SERVICE_URL)), "pong")
        assert "//v3" not in posted[0]
