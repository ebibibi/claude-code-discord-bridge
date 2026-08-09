"""Offering a file, and where its bytes are allowed to go.

The consent handshake puts a URL that arrived over the wire in the middle of a
path ending in "write the contents of a file from this machine to it". Most of
these tests are about that URL and about who is allowed to claim a transfer.
"""

from __future__ import annotations

import pytest

from claude_teams.files import (
    FileTransferRegistry,
    consent_card,
    file_info_card,
    is_microsoft_upload_url,
)

CONVERSATION = "19:abc@thread.tacv2"
OTHER = "19:elsewhere@thread.tacv2"


class TestUploadUrlAllowlist:
    @pytest.mark.parametrize(
        "url",
        [
            "https://contoso.sharepoint.com/_api/upload/abc",
            "https://eu-api.svc.ms/transform/upload?x=1",
            "https://my.onedrive.com/upload",
        ],
    )
    def test_microsoft_hosts_are_accepted(self, url: str) -> None:
        assert is_microsoft_upload_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com/upload",
            # The suffix appears in the query, not the host. A substring check
            # would pass this, and passing it is the whole vulnerability.
            "https://evil.example.com/upload?next=.sharepoint.com",
            # And in the userinfo, which is the other classic way to smuggle a
            # host past a naive check.
            "https://contoso.sharepoint.com@evil.example.com/upload",
            "http://contoso.sharepoint.com/upload",  # not https
            "",
            None,
            12345,
        ],
    )
    def test_everything_else_is_refused(self, url: object) -> None:
        assert not is_microsoft_upload_url(url)


class TestOfferAndClaim:
    def test_an_offer_can_be_claimed_once(self) -> None:
        reg = FileTransferRegistry()
        pending = reg.offer(CONVERSATION, "out.txt", b"data")

        claimed = reg.claim(CONVERSATION, {"ccdb_file": pending.id})
        assert claimed is not None and claimed.content == b"data"
        assert reg.claim(CONVERSATION, {"ccdb_file": pending.id}) is None

    def test_a_claim_from_another_conversation_is_refused(self) -> None:
        # Same rule as prompts, and the same reason: naming a transfer must
        # not be enough to receive it.
        reg = FileTransferRegistry()
        pending = reg.offer(CONVERSATION, "out.txt", b"data")
        assert reg.claim(OTHER, {"ccdb_file": pending.id}) is None
        assert reg.pending_count == 1

    def test_an_unknown_or_malformed_context_is_refused(self) -> None:
        reg = FileTransferRegistry()
        assert reg.claim(CONVERSATION, {"ccdb_file": "nope"}) is None
        assert reg.claim(CONVERSATION, {}) is None
        assert reg.claim(CONVERSATION, "not a dict") is None
        assert reg.claim(CONVERSATION, {"ccdb_file": 42}) is None

    def test_a_declined_offer_is_forgotten(self) -> None:
        reg = FileTransferRegistry()
        pending = reg.offer(CONVERSATION, "out.txt", b"data")
        reg.discard(pending.id)
        assert reg.claim(CONVERSATION, {"ccdb_file": pending.id}) is None
        assert reg.pending_count == 0

    def test_ids_are_unguessable(self) -> None:
        reg = FileTransferRegistry()
        ids = {reg.offer(CONVERSATION, "f.txt", b"x").id for _ in range(50)}
        assert len(ids) == 50
        assert all(len(i) >= 16 for i in ids)


class TestCards:
    def test_the_consent_card_carries_the_size_and_the_context(self) -> None:
        reg = FileTransferRegistry()
        pending = reg.offer(CONVERSATION, "out.txt", b"12345")
        card = consent_card(pending)

        assert card["name"] == "out.txt"
        assert card["content"]["sizeInBytes"] == 5
        # Both contexts must round-trip, so a decline is as identifiable as an
        # accept and does not leave the transfer pending forever.
        assert card["content"]["acceptContext"]["ccdb_file"] == pending.id
        assert card["content"]["declineContext"]["ccdb_file"] == pending.id

    def test_the_info_card_links_to_where_the_file_landed(self) -> None:
        card = file_info_card(
            "out.txt",
            {
                "contentUrl": "https://contoso.sharepoint.com/out.txt",
                "uniqueId": "abc",
                "fileType": "txt",
            },
        )
        assert card["contentUrl"] == "https://contoso.sharepoint.com/out.txt"
        assert card["content"]["uniqueId"] == "abc"
