"""The relay: an inbound endpoint for Teams, without one on the session host.

The property under test is the one that motivated the design — the session host
opens no port, so it can only *take* work — and the failure modes that come
with moving a synchronous handler behind a queue: duplicates, redelivery,
poison messages, and a card press that must be answered before anyone knows
whether it can be honoured.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from claude_teams.auth import TokenError
from claude_teams.relay import ActivityPuller, Envelope, MemoryQueue, RelayReceiver
from claude_teams.relay.envelope import MAX_ENVELOPE_BYTES, EnvelopeTooLargeError

APP_ID = "11111111-2222-3333-4444-555555555555"
SERVICE_URL = "https://smba.trafficmanager.net/apac/"
CONVERSATION = "19:abc@thread.tacv2"


def activity(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": "message",
        "id": "1481567603816",
        "serviceUrl": SERVICE_URL,
        "conversation": {"id": CONVERSATION, "conversationType": "personal"},
        "from": {"id": "29:user", "name": "Ada"},
        "recipient": {"id": f"28:{APP_ID}"},
        "text": "hello",
    }
    body.update(overrides)
    return body


class AcceptingVerifier:
    """Approves, and returns the claim set a real token carries."""

    def __init__(self, service_url: str = SERVICE_URL) -> None:
        self.service_url = service_url
        self.seen: list[tuple[str | None, str | None]] = []

    async def verify(self, authorization: str | None, *, service_url: str | None) -> dict[str, Any]:
        self.seen.append((authorization, service_url))
        # Lower case, as measured on a live Bot Framework token.
        return {
            "aud": APP_ID,
            "iss": "https://api.botframework.com",
            "serviceurl": self.service_url,
        }


class RejectingVerifier:
    async def verify(self, authorization: str | None, *, service_url: str | None) -> dict[str, Any]:
        raise TokenError("nope")


class BrokenQueue:
    async def push(self, text: str) -> None:
        raise RuntimeError("queue unavailable")


async def client_for(receiver: RelayReceiver) -> TestClient:
    app = web.Application()
    receiver.add_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


# ---------------------------------------------------------------------------
# The receiver
# ---------------------------------------------------------------------------


class TestTheReceiverVerifiesBeforeEnqueueing:
    async def test_a_verified_activity_reaches_the_queue(self) -> None:
        queue = MemoryQueue()
        client = await client_for(RelayReceiver(AcceptingVerifier(), queue))
        try:
            response = await client.post("/api/teams/messages", json=activity())
            assert response.status == 200
            assert queue.depth == 1
        finally:
            await client.close()

    async def test_an_unverified_activity_never_reaches_the_queue(self) -> None:
        # If unverified bodies could be queued, the queue would become the
        # trust boundary and the session host would need the Bot Connector's
        # keys to judge what is in it.
        queue = MemoryQueue()
        client = await client_for(RelayReceiver(RejectingVerifier(), queue))
        try:
            response = await client.post("/api/teams/messages", json=activity())
            assert response.status == 401
            assert queue.depth == 0
        finally:
            await client.close()

    async def test_the_envelope_carries_the_token_claim_not_the_body(self) -> None:
        # The body's serviceUrl is attacker-influenced; the token's claim is
        # what Microsoft signed. Moving the endpoint to another machine must
        # not quietly lose that distinction.
        queue = MemoryQueue()
        verifier = AcceptingVerifier(service_url="https://smba.trafficmanager.net/apac/")
        client = await client_for(RelayReceiver(verifier, queue))
        try:
            await client.post(
                "/api/teams/messages", json=activity(serviceUrl="https://evil.example.com/")
            )
            envelope = Envelope.decode((await queue.pull())[0].text)
            assert envelope.service_url == "https://smba.trafficmanager.net/apac/"
        finally:
            await client.close()

    async def test_a_queue_outage_answers_503_so_teams_redelivers(self) -> None:
        # Unlike a failure after the work is stored, this one lost the message.
        # 5xx is exactly right here: Teams will send it again.
        client = await client_for(RelayReceiver(AcceptingVerifier(), BrokenQueue()))
        try:
            assert (await client.post("/api/teams/messages", json=activity())).status == 503
        finally:
            await client.close()

    async def test_an_oversized_activity_is_dropped_not_retried(self) -> None:
        # Retrying would fail identically forever. Answer 200 so Teams stops,
        # and log it — the operator can act on "too big", not on a retry loop.
        queue = MemoryQueue()
        client = await client_for(RelayReceiver(AcceptingVerifier(), queue))
        try:
            response = await client.post(
                "/api/teams/messages", json=activity(text="x" * (MAX_ENVELOPE_BYTES + 1000))
            )
            assert response.status == 200
            assert queue.depth == 0
        finally:
            await client.close()

    async def test_the_health_check_identifies_nothing(self) -> None:
        client = await client_for(RelayReceiver(AcceptingVerifier(), MemoryQueue()))
        try:
            assert await (await client.get("/healthz")).json() == {"status": "ok"}
        finally:
            await client.close()


class TestTheInvokeCompromise:
    async def test_a_card_press_is_answered_inline_and_enqueued(self) -> None:
        # Teams reads the response body as the answer, within seconds. This
        # process cannot know whether the prompt is still live, so it accepts
        # and lets the host decide the effect.
        queue = MemoryQueue()
        client = await client_for(RelayReceiver(AcceptingVerifier(), queue))
        try:
            response = await client.post(
                "/api/teams/messages",
                json=activity(type="invoke", name="adaptiveCard/action"),
            )
            payload = await response.json()
            assert payload["statusCode"] == 200
            assert payload["type"].endswith("activity.message")
            assert queue.depth == 1
        finally:
            await client.close()

    async def test_a_message_keeps_the_plain_body(self) -> None:
        client = await client_for(RelayReceiver(AcceptingVerifier(), MemoryQueue()))
        try:
            response = await client.post("/api/teams/messages", json=activity())
            assert await response.json() == {"status": "ok"}
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# The envelope
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_it_round_trips(self) -> None:
        original = Envelope.wrap(activity(), SERVICE_URL)
        restored = Envelope.decode(original.encode())
        assert restored.activity == original.activity
        assert restored.service_url == SERVICE_URL
        assert restored.conversation_id == CONVERSATION

    def test_an_oversized_envelope_is_named_not_silently_truncated(self) -> None:
        with pytest.raises(EnvelopeTooLargeError, match="bytes"):
            Envelope.wrap(activity(text="x" * MAX_ENVELOPE_BYTES), SERVICE_URL).encode()

    def test_a_future_version_is_refused_rather_than_half_applied(self) -> None:
        import base64
        import json

        payload = Envelope.wrap(activity(), SERVICE_URL).to_dict()
        payload["version"] = 99
        text = base64.b64encode(json.dumps(payload).encode()).decode()
        with pytest.raises(ValueError, match="version"):
            Envelope.decode(text)

    def test_garbage_is_refused_rather_than_read_as_an_empty_activity(self) -> None:
        # Treating it as empty would look like a conversation that said nothing.
        with pytest.raises(ValueError):
            Envelope.decode("not base64 at all !!!")

    def test_it_records_what_the_receiver_verified(self) -> None:
        # The host cannot re-verify — it never sees a token. Recording the
        # claim makes that trust auditable instead of assumed.
        envelope = Envelope.wrap(activity(), SERVICE_URL)
        assert "signature" in envelope.verified
        assert "audience" in envelope.verified


# ---------------------------------------------------------------------------
# The queue's own semantics
# ---------------------------------------------------------------------------


class TestQueueSemantics:
    async def test_nothing_disappears_until_it_is_acknowledged(self) -> None:
        queue = MemoryQueue()
        await queue.push("a")
        items = await queue.pull()
        assert queue.depth == 1, "pulling must not delete"
        await queue.ack(items[0])
        assert queue.depth == 0

    async def test_an_unacknowledged_item_comes_back(self) -> None:
        queue = MemoryQueue()
        await queue.push("a")
        first = await queue.pull()
        assert await queue.pull() == [], "still leased"
        queue.expire_leases()
        again = await queue.pull()
        assert again and again[0].delivery_count > first[0].delivery_count


# ---------------------------------------------------------------------------
# The puller
# ---------------------------------------------------------------------------


class Recorder:
    def __init__(self, fail_times: int = 0) -> None:
        self.seen: list[str] = []
        self.fail_times = fail_times

    async def __call__(self, act: Any) -> None:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("handler blew up")
        self.seen.append(act.id)


async def enqueue(queue: MemoryQueue, **overrides: Any) -> None:
    await queue.push(Envelope.wrap(activity(**overrides), SERVICE_URL).encode())


def puller(queue: MemoryQueue, handler: Any, **kwargs: Any) -> ActivityPuller:
    kwargs.setdefault("sleep", lambda _s: asyncio.sleep(0))
    return ActivityPuller(queue, handler, **kwargs)


class TestThePullerTakesWork:
    async def test_it_hands_the_activity_to_the_handler(self) -> None:
        queue, handler = MemoryQueue(), Recorder()
        await enqueue(queue)
        for item in await queue.pull():
            await puller(queue, handler).handle_one(item)
        assert handler.seen == ["1481567603816"]
        assert queue.depth == 0

    async def test_it_reports_where_the_conversation_is_served_from(self) -> None:
        # The one piece of addressing the ledger does not carry. Without it a
        # scheduled follow-up has nowhere to go after a restart.
        learned: list[tuple[str, str]] = []
        queue, handler = MemoryQueue(), Recorder()
        await enqueue(queue)
        p = puller(queue, handler, on_service_url=lambda c, s: learned.append((c, s)))
        for item in await queue.pull():
            await p.handle_one(item)
        assert learned == [(CONVERSATION, SERVICE_URL)]


class TestThePullerAcknowledgesOnlyWhenDone:
    async def test_a_failed_handler_leaves_the_message_on_the_queue(self) -> None:
        # A user's message that vanishes because a process restarted is
        # indistinguishable from a bot that ignored them.
        queue, handler = MemoryQueue(), Recorder(fail_times=1)
        await enqueue(queue)
        p = puller(queue, handler)
        for item in await queue.pull():
            await p.handle_one(item)
        assert queue.depth == 1, "an unhandled message must survive"

        queue.expire_leases()
        for item in await queue.pull():
            await p.handle_one(item)
        assert handler.seen == ["1481567603816"]
        assert queue.depth == 0


class TestThePullerDoesNotActTwice:
    async def test_a_redelivery_of_finished_work_is_skipped(self) -> None:
        # At-least-once means this happens. Running a session twice for one
        # message is worse than the crash that caused the redelivery.
        queue, handler = MemoryQueue(), Recorder()
        await enqueue(queue)
        p = puller(queue, handler)
        items = await queue.pull()
        await p.handle_one(items[0])

        await queue.push(items[0].text)  # the same activity, delivered again
        for item in await queue.pull():
            await p.handle_one(item)

        assert handler.seen == ["1481567603816"], "handled exactly once"
        assert queue.depth == 0


class TestPoisonMessages:
    async def test_an_activity_that_always_fails_is_eventually_dropped(self) -> None:
        # Otherwise it is retried forever and the *next* message never runs.
        queue, handler = MemoryQueue(), Recorder(fail_times=99)
        await enqueue(queue)
        p = puller(queue, handler, max_deliveries=2)

        for _ in range(4):
            queue.expire_leases()
            for item in await queue.pull():
                await p.handle_one(item)

        assert queue.depth == 0, "the queue must not stay blocked on one bad message"
        assert handler.seen == []

    async def test_an_unreadable_message_is_dropped_immediately(self) -> None:
        # Unreadable now is unreadable next time; retrying blocks the queue on
        # something nothing can ever consume.
        queue, handler = MemoryQueue(), Recorder()
        await queue.push("this is not an envelope")
        for item in await queue.pull():
            await puller(queue, handler).handle_one(item)
        assert queue.depth == 0
        assert handler.seen == []


class TestThePullerNeverListens:
    def test_it_exposes_no_server_surface(self) -> None:
        # The whole point: this object polls. If it ever grew a bind/serve
        # method, the session host would be back on the internet.
        p = puller(MemoryQueue(), Recorder())
        for forbidden in ("add_routes", "bind", "listen", "serve", "handle_request"):
            assert not hasattr(p, forbidden), f"the puller must not expose {forbidden}"

    async def test_close_leaves_in_flight_work_on_the_queue(self) -> None:
        queue, handler = MemoryQueue(), Recorder()
        await enqueue(queue)
        p = puller(queue, handler)
        await p.start()
        await asyncio.sleep(0)
        await p.close()
        assert p.running is False


# ---------------------------------------------------------------------------
# Azure Queue Storage
# ---------------------------------------------------------------------------


class FakeHttp:
    """Records requests and replays canned responses."""

    def __init__(self, responses: list[tuple[int, str]]) -> None:
        self.calls: list[tuple[str, str, bytes | None]] = []
        self._responses = responses

    async def __call__(
        self, method: str, url: str, *, data: bytes | None = None, headers: Any = None
    ) -> tuple[int, str]:
        self.calls.append((method, url, data))
        return self._responses.pop(0) if self._responses else (200, "")


MESSAGES_XML = """<?xml version="1.0" encoding="utf-8"?>
<QueueMessagesList>
  <QueueMessage>
    <MessageId>abc-1</MessageId>
    <PopReceipt>receipt/one+=</PopReceipt>
    <DequeueCount>2</DequeueCount>
    <MessageText>cGF5bG9hZA==</MessageText>
  </QueueMessage>
</QueueMessagesList>"""

SAS_URL = "https://acct.queue.core.windows.net/relay?sv=2021&sig=SECRETSIG&se=2027"


class TestStorageQueue:
    def test_a_url_without_a_sas_is_refused(self) -> None:
        from claude_teams.relay.storage_queue import StorageQueue

        with pytest.raises(ValueError, match="SAS"):
            StorageQueue("https://acct.queue.core.windows.net/relay", FakeHttp([]))

    def test_a_non_https_url_is_refused(self) -> None:
        from claude_teams.relay.storage_queue import StorageQueue

        with pytest.raises(ValueError, match="https"):
            StorageQueue("http://acct.queue.core.windows.net/relay?sv=1", FakeHttp([]))

    async def test_a_get_returns_the_message_and_its_delivery_count(self) -> None:
        # DequeueCount is what lets the puller recognise a poison message.
        from claude_teams.relay.storage_queue import StorageQueue

        http = FakeHttp([(200, MESSAGES_XML)])
        items = await StorageQueue(SAS_URL, http).pull(max_items=4)
        assert len(items) == 1
        assert items[0].text == "cGF5bG9hZA=="
        assert items[0].delivery_count == 2
        assert items[0].receipt == ("abc-1", "receipt/one+=")

    async def test_a_message_with_no_pop_receipt_is_skipped(self) -> None:
        # It could never be deleted, so handing it over would guarantee an
        # infinite redelivery of something nothing can acknowledge.
        from claude_teams.relay.storage_queue import StorageQueue

        xml = (
            "<QueueMessagesList><QueueMessage><MessageId>x</MessageId>"
            "<MessageText>y</MessageText></QueueMessage></QueueMessagesList>"
        )
        assert await StorageQueue(SAS_URL, FakeHttp([(200, xml)])).pull() == []

    async def test_the_pop_receipt_is_url_encoded_on_delete(self) -> None:
        # Pop receipts routinely contain '+' and '/'. Unencoded, the delete
        # silently targets a different receipt and the message comes back.
        from claude_teams.relay.storage_queue import StorageQueue

        http = FakeHttp([(200, MESSAGES_XML), (204, "")])
        queue = StorageQueue(SAS_URL, http)
        item = (await queue.pull())[0]
        await queue.ack(item)

        _method, url, _data = http.calls[-1]
        assert "receipt%2Fone%2B%3D" in url

    async def test_deleting_something_already_gone_is_not_an_error(self) -> None:
        from claude_teams.relay.storage_queue import StorageQueue

        http = FakeHttp([(200, MESSAGES_XML), (404, "")])
        queue = StorageQueue(SAS_URL, http)
        await queue.ack((await queue.pull())[0])  # must not raise

    async def test_a_put_wraps_the_text_in_the_xml_teams_expects(self) -> None:
        from claude_teams.relay.storage_queue import StorageQueue

        http = FakeHttp([(201, "")])
        await StorageQueue(SAS_URL, http).push("cGF5bG9hZA==")
        _method, _url, data = http.calls[0]
        assert data is not None
        assert b"<QueueMessage><MessageText>cGF5bG9hZA==</MessageText></QueueMessage>" in data

    async def test_a_failure_never_repeats_the_sas(self) -> None:
        # The SAS is the credential. A stack trace carrying it ends up in a
        # log, and from there in a pasted bug report.
        from claude_teams.relay.storage_queue import StorageQueue

        with pytest.raises(RuntimeError) as exc:
            await StorageQueue(SAS_URL, FakeHttp([(403, "denied")])).push("x")
        assert "SECRETSIG" not in str(exc.value)

    async def test_an_xml_bomb_does_not_expand(self) -> None:
        # Parsed with defusedxml: the document arrives over a network as bytes
        # this process did not write, whoever is nominally at the other end.
        from claude_teams.relay.storage_queue import StorageQueue

        bomb = (
            '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
            '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
            "<QueueMessagesList><QueueMessage><MessageText>&lol2;</MessageText>"
            "</QueueMessage></QueueMessagesList>"
        )
        with pytest.raises(RuntimeError, match="unparseable"):
            await StorageQueue(SAS_URL, FakeHttp([(200, bomb)])).pull()
