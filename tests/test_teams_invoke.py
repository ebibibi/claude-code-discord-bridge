"""Routing a card press back to the session that is waiting for it.

A card action does not arrive like a message. Teams sends an ``invoke``
activity and expects the *HTTP response body* to be the answer — so an invoke
answered with a bare 200, or answered late, shows the user an error even though
the press worked. That asymmetry is what these tests hold in place.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from claude_teams.endpoint import TeamsEndpoint
from claude_teams.interactions import InteractionRegistry

APP_ID = "11111111-2222-3333-4444-555555555555"
SERVICE_URL = "https://smba.trafficmanager.net/emea/"
CONVERSATION = "19:abc@thread.tacv2"


def invoke_body(data: dict[str, Any], *, conversation: str = CONVERSATION) -> dict[str, Any]:
    return {
        "type": "invoke",
        "name": "adaptiveCard/action",
        "id": "1481567603816",
        "serviceUrl": SERVICE_URL,
        "conversation": {"id": conversation},
        "from": {"id": "29:user", "name": "Ada"},
        "recipient": {"id": f"28:{APP_ID}"},
        "value": {"action": {"type": "Action.Execute", "verb": "ccdb.action", "data": data}},
    }


class AcceptingVerifier:
    async def verify(self, authorization: str | None, *, service_url: str | None) -> dict[str, Any]:
        return {"aud": APP_ID}


class RejectingVerifier:
    async def verify(self, authorization: str | None, *, service_url: str | None) -> dict[str, Any]:
        from claude_teams.auth import TokenError

        raise TokenError("nope")


class NullConnector:
    async def send_text(self, ref: Any, text: str) -> None:
        return None


async def client_for(endpoint: TeamsEndpoint) -> TestClient:
    app = web.Application()
    endpoint.add_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def build(registry: InteractionRegistry, *, verifier: Any = None) -> TeamsEndpoint:
    return TeamsEndpoint(
        app_id=APP_ID,
        verifier=verifier or AcceptingVerifier(),
        connector=NullConnector(),
        interactions=registry,
    )


class TestTheInvokeResponse:
    async def test_an_accepted_press_answers_inline(self) -> None:
        registry = InteractionRegistry()
        pending = registry.register_choice(CONVERSATION, values=("allow",), multi_select=False)
        endpoint = build(registry)
        client = await client_for(endpoint)
        try:
            response = await client.post(
                endpoint.path,
                json=invoke_body({"ccdb_prompt": pending.id, "ccdb_value": "allow"}),
            )
            assert response.status == 200
            payload = await response.json()
            # Not a bare {"status": "ok"} — Teams reads this body as the answer.
            assert payload["statusCode"] == 200
            assert payload["type"].endswith("activity.message")
        finally:
            await client.close()

    async def test_the_waiting_caller_gets_the_value(self) -> None:
        registry = InteractionRegistry()
        pending = registry.register_choice(CONVERSATION, values=("allow",), multi_select=False)
        endpoint = build(registry)
        client = await client_for(endpoint)
        try:
            await client.post(
                endpoint.path,
                json=invoke_body({"ccdb_prompt": pending.id, "ccdb_value": "allow"}),
            )
            assert pending.future.result() == ("allow",)
        finally:
            await client.close()

    async def test_a_refused_press_still_answers_200_with_a_message(self) -> None:
        # An expired prompt is an ordinary thing for a user to press. Failing
        # the invoke would show them an error for doing nothing wrong.
        endpoint = build(InteractionRegistry())
        client = await client_for(endpoint)
        try:
            response = await client.post(
                endpoint.path, json=invoke_body({"ccdb_prompt": "gone", "ccdb_value": "allow"})
            )
            assert response.status == 200
            assert (await response.json())["statusCode"] == 200
        finally:
            await client.close()

    async def test_the_refusal_does_not_say_why(self) -> None:
        # "Wrong conversation" and "expired" are both free information to
        # whoever is probing.
        registry = InteractionRegistry()
        pending = registry.register_choice(CONVERSATION, values=("allow",), multi_select=False)
        endpoint = build(registry)
        client = await client_for(endpoint)
        try:
            response = await client.post(
                endpoint.path,
                json=invoke_body(
                    {"ccdb_prompt": pending.id, "ccdb_value": "allow"},
                    conversation="19:elsewhere@thread.tacv2",
                ),
            )
            text = await response.text()
            assert "conversation" not in text.lower()
            assert not pending.future.done()
        finally:
            await client.close()


class TestAuthenticationStillApplies:
    async def test_an_unverified_invoke_resolves_nothing(self) -> None:
        # The prompt being answered here can be a tool-permission request, so
        # this is the same boundary as everything else — not a lighter one
        # because the payload happens to be a button press.
        registry = InteractionRegistry()
        pending = registry.register_choice(CONVERSATION, values=("allow",), multi_select=False)
        endpoint = build(registry, verifier=RejectingVerifier())
        client = await client_for(endpoint)
        try:
            response = await client.post(
                endpoint.path,
                json=invoke_body({"ccdb_prompt": pending.id, "ccdb_value": "allow"}),
            )
            assert response.status == 401
            assert not pending.future.done()
        finally:
            await client.close()


class TestOtherInvokes:
    async def test_an_unknown_invoke_name_is_answered_without_error(self) -> None:
        # Teams sends invokes ccdb does not implement (task/fetch, and more
        # over time). Answering them with a failure surfaces as a broken bot.
        endpoint = build(InteractionRegistry())
        client = await client_for(endpoint)
        try:
            body = invoke_body({})
            body["name"] = "task/fetch"
            response = await client.post(endpoint.path, json=body)
            assert response.status == 200
            assert (await response.json())["statusCode"] == 200
        finally:
            await client.close()

    async def test_an_invoke_with_no_action_data_is_refused_quietly(self) -> None:
        endpoint = build(InteractionRegistry())
        client = await client_for(endpoint)
        try:
            body = invoke_body({})
            body["value"] = "not an object"
            response = await client.post(endpoint.path, json=body)
            assert response.status == 200
        finally:
            await client.close()


class TestMessagesAreUnaffected:
    async def test_a_message_still_gets_the_plain_ok_body(self) -> None:
        # Only invokes carry an inline answer; changing the message response
        # would be a protocol error in the other direction.
        seen: list[str] = []

        async def on_message(activity: Any) -> None:
            seen.append(activity.text)

        endpoint = TeamsEndpoint(
            app_id=APP_ID,
            verifier=AcceptingVerifier(),
            connector=NullConnector(),
            interactions=InteractionRegistry(),
            on_message=on_message,
        )
        client = await client_for(endpoint)
        try:
            body = invoke_body({})
            body["type"] = "message"
            body["text"] = "hello"
            response = await client.post(endpoint.path, json=body)
            assert (await response.json()) == {"status": "ok"}
            assert seen == ["hello"]
        finally:
            await client.close()
