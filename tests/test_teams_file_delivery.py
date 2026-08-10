"""Delivering a file end to end: offer, accept, upload.

The path being tested ends with "write the contents of a local file to a URL
that arrived over the wire". Half of these tests are about refusing to do that.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from claude_code_core.frontend import OutboundFile
from claude_teams.conversation import ConversationRef
from claude_teams.endpoint import TeamsEndpoint
from claude_teams.files import FileTransferRegistry
from claude_teams.pacer import UpdatePacer
from claude_teams.surface import TeamsSurface

APP_ID = "11111111-2222-3333-4444-555555555555"
SERVICE_URL = "https://smba.trafficmanager.net/emea/"
CONVERSATION = "19:abc@thread.tacv2"
GOOD_UPLOAD_URL = "https://contoso.sharepoint.com/_api/upload/abc"

PERSONAL = ConversationRef(
    service_url=SERVICE_URL, conversation_id=CONVERSATION, conversation_type="personal"
)
CHANNEL = ConversationRef(
    service_url=SERVICE_URL, conversation_id=CONVERSATION, conversation_type="channel"
)


class Recorder:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_activity(self, ref: ConversationRef, body: dict[str, Any]) -> str:
        self.sent.append(body)
        return f"activity-{len(self.sent)}"

    async def update_activity(self, ref: Any, activity_id: str, body: Any) -> None:
        return None

    async def send_text(self, ref: Any, text: str) -> None:
        self.sent.append({"type": "message", "text": text})

    @property
    def consent_cards(self) -> list[dict[str, Any]]:
        return [
            a
            for b in self.sent
            for a in b.get("attachments", [])
            if a.get("contentType", "").endswith("file.consent")
        ]

    @property
    def info_cards(self) -> list[dict[str, Any]]:
        return [
            a
            for b in self.sent
            for a in b.get("attachments", [])
            if a.get("contentType", "").endswith("file.info")
        ]

    @property
    def texts(self) -> list[str]:
        return [b["text"] for b in self.sent if "text" in b]


class Uploader:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self.fail = fail

    async def __call__(self, url: str, content: bytes) -> None:
        if self.fail:
            raise RuntimeError("upload rejected")
        self.calls.append((url, content))


class AcceptingVerifier:
    async def verify(self, authorization: str | None, *, service_url: str | None) -> dict[str, Any]:
        return {"aud": APP_ID}


def surface(recorder: Recorder, files: FileTransferRegistry, ref: ConversationRef) -> TeamsSurface:
    return TeamsSurface(
        thread_key=9_007_199_254_740_993,
        ref=ref,
        connector=recorder,
        pacer=UpdatePacer(0.001),
        files=files,
    )


def endpoint(
    recorder: Recorder, files: FileTransferRegistry, uploader: Uploader | None
) -> TeamsEndpoint:
    return TeamsEndpoint(
        app_id=APP_ID,
        verifier=AcceptingVerifier(),
        connector=recorder,
        files=files,
        upload_bytes=uploader,
    )


def consent_invoke(
    context: Any, *, action: str = "accept", upload_url: str = GOOD_UPLOAD_URL
) -> dict[str, Any]:
    return {
        "type": "invoke",
        "name": "fileConsent/invoke",
        "id": "1481567603816",
        "serviceUrl": SERVICE_URL,
        "conversation": {"id": CONVERSATION, "conversationType": "personal"},
        "from": {"id": "29:user"},
        "recipient": {"id": f"28:{APP_ID}"},
        "value": {
            "type": "fileUpload",
            "action": action,
            "context": context,
            "uploadInfo": {
                "uploadUrl": upload_url,
                "contentUrl": "https://contoso.sharepoint.com/out.txt",
                "name": "out.txt",
                "uniqueId": "abc",
                "fileType": "txt",
            },
        },
    }


async def client_for(ep: TeamsEndpoint) -> TestClient:
    app = web.Application()
    ep.add_routes(app)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


class TestOfferingInAPersonalChat:
    async def test_every_file_gets_a_consent_card(self) -> None:
        recorder, files = Recorder(), FileTransferRegistry()
        s = surface(recorder, files, PERSONAL)
        await s.deliver_files(
            [OutboundFile(display_name=f"f{i}.txt", blob=b"data") for i in range(5)]
        )
        assert len(recorder.consent_cards) == 5
        assert files.pending_count == 5

    async def test_a_file_from_disk_is_read(self, tmp_path) -> None:
        path = tmp_path / "out.txt"
        path.write_bytes(b"on disk")
        recorder, files = Recorder(), FileTransferRegistry()
        s = surface(recorder, files, PERSONAL)

        await s.deliver_files([OutboundFile(display_name="out.txt", path=str(path))])
        assert recorder.consent_cards[0]["content"]["sizeInBytes"] == 7

    async def test_an_unreadable_file_is_reported_not_swallowed(self, tmp_path) -> None:
        recorder, files = Recorder(), FileTransferRegistry()
        s = surface(recorder, files, PERSONAL)

        await s.deliver_files(
            [OutboundFile(display_name="gone.txt", path=str(tmp_path / "gone.txt"))]
        )
        assert not recorder.consent_cards
        assert "gone.txt" in recorder.texts[0]

    async def test_an_oversized_file_is_refused_rather_than_truncated(self) -> None:
        # Truncating hands over a file that looks complete and is not, which
        # is worse than not sending it.
        recorder, files = Recorder(), FileTransferRegistry()
        s = surface(recorder, files, PERSONAL)
        limit = s.capabilities.max_file_bytes

        await s.deliver_files([OutboundFile(display_name="big.bin", blob=b"x" * (limit + 1))])
        assert not recorder.consent_cards
        assert "big.bin" in recorder.texts[0]


class TestChannelsSayWhatTheyCannotDo:
    async def test_a_channel_names_the_files_and_says_they_were_not_sent(self) -> None:
        recorder, files = Recorder(), FileTransferRegistry()
        s = surface(recorder, files, CHANNEL)

        await s.deliver_files([OutboundFile(display_name="a.txt", blob=b"x")])
        assert not recorder.consent_cards
        assert "a.txt" in recorder.texts[0]
        assert "not" in recorder.texts[0].lower()


class TestAcceptingATransfer:
    async def test_accept_uploads_the_bytes_and_posts_the_link(self) -> None:
        recorder, files, uploader = Recorder(), FileTransferRegistry(), Uploader()
        s = surface(recorder, files, PERSONAL)
        await s.deliver_files([OutboundFile(display_name="out.txt", blob=b"payload")])
        context = recorder.consent_cards[0]["content"]["acceptContext"]

        ep = endpoint(recorder, files, uploader)
        client = await client_for(ep)
        try:
            response = await client.post(ep.path, json=consent_invoke(context))
            assert response.status == 200
            assert uploader.calls == [(GOOD_UPLOAD_URL, b"payload")]
            assert recorder.info_cards, "the user needs a link to what just landed"
        finally:
            await client.close()

    async def test_decline_forgets_the_transfer_without_uploading(self) -> None:
        recorder, files, uploader = Recorder(), FileTransferRegistry(), Uploader()
        s = surface(recorder, files, PERSONAL)
        await s.deliver_files([OutboundFile(display_name="out.txt", blob=b"payload")])
        context = recorder.consent_cards[0]["content"]["declineContext"]

        ep = endpoint(recorder, files, uploader)
        client = await client_for(ep)
        try:
            await client.post(ep.path, json=consent_invoke(context, action="decline"))
            assert uploader.calls == []
            assert files.pending_count == 0
        finally:
            await client.close()

    async def test_accepting_twice_uploads_once(self) -> None:
        recorder, files, uploader = Recorder(), FileTransferRegistry(), Uploader()
        s = surface(recorder, files, PERSONAL)
        await s.deliver_files([OutboundFile(display_name="out.txt", blob=b"payload")])
        context = recorder.consent_cards[0]["content"]["acceptContext"]

        ep = endpoint(recorder, files, uploader)
        client = await client_for(ep)
        try:
            await client.post(ep.path, json=consent_invoke(context))
            await client.post(ep.path, json=consent_invoke(context))
            assert len(uploader.calls) == 1
        finally:
            await client.close()


class TestWhereTheBytesMayGo:
    async def test_an_upload_url_outside_microsoft_is_refused(self) -> None:
        # The one place something off the wire decides where the contents of a
        # local file are written. The invoke is authenticated, so this is
        # defence in depth — and it is the difference between a file transfer
        # and an exfiltration primitive if anything upstream is wrong.
        recorder, files, uploader = Recorder(), FileTransferRegistry(), Uploader()
        s = surface(recorder, files, PERSONAL)
        await s.deliver_files([OutboundFile(display_name="out.txt", blob=b"secret")])
        context = recorder.consent_cards[0]["content"]["acceptContext"]

        ep = endpoint(recorder, files, uploader)
        client = await client_for(ep)
        try:
            response = await client.post(
                ep.path,
                json=consent_invoke(context, upload_url="https://evil.example.com/collect"),
            )
            assert response.status == 200
            assert uploader.calls == [], "not one byte may leave for an unrecognised host"
        finally:
            await client.close()

    async def test_an_accept_from_another_conversation_uploads_nothing(self) -> None:
        recorder, files, uploader = Recorder(), FileTransferRegistry(), Uploader()
        s = surface(recorder, files, PERSONAL)
        await s.deliver_files([OutboundFile(display_name="out.txt", blob=b"secret")])
        context = recorder.consent_cards[0]["content"]["acceptContext"]

        ep = endpoint(recorder, files, uploader)
        client = await client_for(ep)
        try:
            body = consent_invoke(context)
            body["conversation"] = {"id": "19:elsewhere@thread.tacv2"}
            await client.post(ep.path, json=body)
            assert uploader.calls == []
            assert files.pending_count == 1, "the real recipient's offer must still stand"
        finally:
            await client.close()

    async def test_an_unknown_context_uploads_nothing(self) -> None:
        recorder, files, uploader = Recorder(), FileTransferRegistry(), Uploader()
        ep = endpoint(recorder, files, uploader)
        client = await client_for(ep)
        try:
            response = await client.post(ep.path, json=consent_invoke({"ccdb_file": "nope"}))
            assert response.status == 200
            assert uploader.calls == []
        finally:
            await client.close()


class TestFailures:
    async def test_a_failed_upload_tells_the_user_and_answers_200(self) -> None:
        recorder, files = Recorder(), FileTransferRegistry()
        uploader = Uploader(fail=True)
        s = surface(recorder, files, PERSONAL)
        await s.deliver_files([OutboundFile(display_name="out.txt", blob=b"payload")])
        context = recorder.consent_cards[0]["content"]["acceptContext"]

        ep = endpoint(recorder, files, uploader)
        client = await client_for(ep)
        try:
            response = await client.post(ep.path, json=consent_invoke(context))
            assert response.status == 200
            assert not recorder.info_cards, "no link to a file that never landed"
        finally:
            await client.close()

    async def test_a_deployment_with_no_upload_transport_refuses_cleanly(self) -> None:
        recorder, files = Recorder(), FileTransferRegistry()
        s = surface(recorder, files, PERSONAL)
        await s.deliver_files([OutboundFile(display_name="out.txt", blob=b"payload")])
        context = recorder.consent_cards[0]["content"]["acceptContext"]

        ep = endpoint(recorder, files, None)
        client = await client_for(ep)
        try:
            response = await client.post(ep.path, json=consent_invoke(context))
            assert response.status == 200
            assert not recorder.info_cards
        finally:
            await client.close()
