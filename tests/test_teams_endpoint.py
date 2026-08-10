"""The inbound endpoint: what it answers, and what it refuses to do.

This is the first piece of ccdb that anyone on the internet can reach. The
tests are written from that angle — the interesting assertions are about
requests that must *not* result in work being done.
"""

from __future__ import annotations

import json
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from claude_teams.activity import InboundActivity
from claude_teams.auth import TokenError
from claude_teams.endpoint import TeamsEndpoint

APP_ID = "11111111-2222-3333-4444-555555555555"
SERVICE_URL = "https://smba.trafficmanager.net/emea/"


def message_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "message",
        "id": "1481567603816",
        "serviceUrl": SERVICE_URL,
        "conversation": {"id": "19:abc@thread.tacv2;messageid=1481567603816"},
        "from": {"id": "29:user-aad-id", "name": "Ada"},
        "recipient": {"id": f"28:{APP_ID}"},
        "text": "hello",
    }
    body.update(overrides)
    return body


class AcceptingVerifier:
    def __init__(self) -> None:
        self.seen: list[tuple[str | None, str | None]] = []

    async def verify(self, authorization: str | None, *, service_url: str | None) -> dict[str, Any]:
        self.seen.append((authorization, service_url))
        return {"aud": APP_ID, "serviceUrl": service_url}


class RejectingVerifier:
    async def verify(self, authorization: str | None, *, service_url: str | None) -> dict[str, Any]:
        raise TokenError("nope")


class RecordingConnector:
    def __init__(self) -> None:
        self.sent: list[tuple[InboundActivity, str]] = []

    async def send_text(self, activity: InboundActivity, text: str) -> None:
        self.sent.append((activity, text))


class ExplodingConnector:
    async def send_text(self, activity: InboundActivity, text: str) -> None:
        raise RuntimeError("service unavailable")


async def client_for(endpoint: TeamsEndpoint) -> TestClient:
    app = web.Application()
    endpoint.add_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


def build(
    *,
    verifier: Any | None = None,
    connector: Any | None = None,
    **overrides: Any,
) -> TeamsEndpoint:
    return TeamsEndpoint(
        app_id=APP_ID,
        verifier=verifier or AcceptingVerifier(),
        connector=connector or RecordingConnector(),
        **overrides,
    )


class TestAuthentication:
    async def test_a_rejected_token_gets_401_and_does_no_work(self) -> None:
        connector = RecordingConnector()
        endpoint = build(verifier=RejectingVerifier(), connector=connector)
        client = await client_for(endpoint)
        try:
            response = await client.post(endpoint.path, json=message_body())
            assert response.status == 401
            assert connector.sent == []
        finally:
            await client.close()

    async def test_the_401_body_says_nothing_about_why(self) -> None:
        # Distinguishing "expired" from "wrong audience" in a response is free
        # reconnaissance for whoever is probing the endpoint.
        endpoint = build(verifier=RejectingVerifier())
        client = await client_for(endpoint)
        try:
            response = await client.post(endpoint.path, json=message_body())
            assert "nope" not in (await response.text())
        finally:
            await client.close()

    async def test_the_service_url_from_the_body_is_handed_to_the_verifier(self) -> None:
        # The endpoint must not verify the token in isolation: binding it to
        # the body's serviceUrl is what stops a replayed token from redirecting
        # this process's authenticated outbound calls.
        verifier = AcceptingVerifier()
        endpoint = build(verifier=verifier)
        client = await client_for(endpoint)
        try:
            await client.post(
                endpoint.path,
                json=message_body(),
                headers={"Authorization": "Bearer x"},
            )
            assert verifier.seen == [("Bearer x", SERVICE_URL)]
        finally:
            await client.close()


class TestMalformedBodies:
    async def test_a_body_that_is_not_json_gets_400(self) -> None:
        endpoint = build()
        client = await client_for(endpoint)
        try:
            response = await client.post(
                endpoint.path,
                data="not json",
                headers={"Content-Type": "application/json"},
            )
            assert response.status == 400
        finally:
            await client.close()

    async def test_an_activity_without_a_conversation_gets_400(self) -> None:
        endpoint = build()
        client = await client_for(endpoint)
        try:
            body = message_body()
            del body["conversation"]
            response = await client.post(endpoint.path, json=body)
            assert response.status == 400
        finally:
            await client.close()


class TestEcho:
    async def test_a_message_is_echoed(self) -> None:
        connector = RecordingConnector()
        endpoint = build(connector=connector)
        client = await client_for(endpoint)
        try:
            response = await client.post(endpoint.path, json=message_body(text="ping"))
            assert response.status == 200
            assert len(connector.sent) == 1
            assert "ping" in connector.sent[0][1]
        finally:
            await client.close()

    async def test_the_bot_does_not_answer_itself(self) -> None:
        # Teams echoes a bot's own channel posts back to it. Without this the
        # first reply becomes the next request and the loop runs as fast as the
        # rate limiter allows.
        connector = RecordingConnector()
        endpoint = build(connector=connector)
        client = await client_for(endpoint)
        try:
            body = message_body(**{"from": {"id": APP_ID, "name": "Relay"}})
            response = await client.post(endpoint.path, json=body)
            assert response.status == 200
            assert connector.sent == []
        finally:
            await client.close()

    async def test_non_message_activities_are_accepted_and_ignored(self) -> None:
        # conversationUpdate arrives whenever anyone joins a channel the app is
        # installed in. Answering 4xx to it makes Teams retry, and retry.
        connector = RecordingConnector()
        endpoint = build(connector=connector)
        client = await client_for(endpoint)
        try:
            response = await client.post(
                endpoint.path, json=message_body(type="conversationUpdate")
            )
            assert response.status == 200
            assert connector.sent == []
        finally:
            await client.close()

    async def test_a_custom_handler_replaces_the_echo(self) -> None:
        seen: list[InboundActivity] = []

        async def handler(activity: InboundActivity) -> None:
            seen.append(activity)

        connector = RecordingConnector()
        endpoint = build(connector=connector, on_message=handler)
        client = await client_for(endpoint)
        try:
            await client.post(endpoint.path, json=message_body())
            assert len(seen) == 1
            assert seen[0].conversation_id.startswith("19:")
            assert connector.sent == []
        finally:
            await client.close()


class TestDownstreamFailures:
    async def test_a_failing_send_still_answers_200(self) -> None:
        # A 5xx makes Teams redeliver the same activity, so a transient outage
        # downstream turns into the user's message being processed repeatedly.
        # The failure belongs in the log, not in the HTTP status.
        endpoint = build(connector=ExplodingConnector())
        client = await client_for(endpoint)
        try:
            response = await client.post(endpoint.path, json=message_body())
            assert response.status == 200
        finally:
            await client.close()


class TestRouting:
    async def test_the_path_comes_from_configuration(self) -> None:
        endpoint = build(path="/custom/teams")
        assert endpoint.path == "/custom/teams"
        client = await client_for(endpoint)
        try:
            assert (await client.post("/custom/teams", json=message_body())).status == 200
            assert (await client.post("/api/teams/messages", json=message_body())).status == 404
        finally:
            await client.close()

    async def test_get_is_not_a_way_in(self) -> None:
        endpoint = build()
        client = await client_for(endpoint)
        try:
            assert (await client.get(endpoint.path)).status == 405
        finally:
            await client.close()


class TestPayloadSize:
    async def test_an_oversized_body_is_refused_before_it_is_parsed(self) -> None:
        # Unauthenticated callers can post anything. Reading it all into memory
        # to find out it was junk is the cheapest denial of service there is.
        endpoint = build(max_body_bytes=1024)
        client = await client_for(endpoint)
        try:
            body = json.dumps(message_body(text="x" * 5000))
            response = await client.post(
                endpoint.path, data=body, headers={"Content-Type": "application/json"}
            )
            assert response.status == 413
        finally:
            await client.close()
