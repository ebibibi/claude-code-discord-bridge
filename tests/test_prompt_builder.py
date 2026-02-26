"""Tests for prompt_builder module: attachment handling and prompt construction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.cogs.prompt_builder import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    MAX_TOTAL_BYTES,
    build_prompt_and_images,
)


def _make_attachment(
    filename: str = "test.txt",
    content_type: str = "text/plain",
    size: int = 100,
    content: bytes = b"hello world",
    url: str = "https://cdn.discordapp.com/attachments/123/456/test.txt",
) -> MagicMock:
    att = MagicMock(spec=discord.Attachment)
    att.filename = filename
    att.content_type = content_type
    att.size = size
    att.url = url
    att.read = AsyncMock(return_value=content)
    return att


def _make_message(content: str = "my message", attachments: list | None = None) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.content = content
    msg.attachments = attachments or []
    return msg


class TestBuildPromptAndImages:
    """Tests for the build_prompt_and_images function (attachment handling)."""

    @pytest.mark.asyncio
    async def test_no_attachments_returns_content(self) -> None:
        msg = _make_message(content="hello")
        prompt, images = await build_prompt_and_images(msg)
        assert prompt == "hello"
        assert images == []

    @pytest.mark.asyncio
    async def test_text_attachment_appended(self) -> None:
        att = _make_attachment(filename="notes.txt", content=b"file content here")
        msg = _make_message(content="check this", attachments=[att])

        prompt, _ = await build_prompt_and_images(msg)

        assert "check this" in prompt
        assert "notes.txt" in prompt
        assert "file content here" in prompt

    @pytest.mark.asyncio
    async def test_image_attachment_returns_cdn_url(self) -> None:
        """Images are returned as Discord CDN URLs, NOT downloaded to tempfiles."""
        cdn_url = "https://cdn.discordapp.com/attachments/111/222/image.png"
        att = _make_attachment(
            filename="image.png",
            content_type="image/png",
            size=100,
            url=cdn_url,
        )
        msg = _make_message(content="see image", attachments=[att])

        prompt, image_urls = await build_prompt_and_images(msg)

        assert prompt == "see image"
        assert len(image_urls) == 1
        assert image_urls[0] == cdn_url
        att.read.assert_not_called()

    @pytest.mark.asyncio
    async def test_binary_non_image_skipped(self) -> None:
        """Non-image binary files (e.g. zip) are still silently skipped."""
        att = _make_attachment(
            filename="archive.zip",
            content_type="application/zip",
            content=b"PK...",
        )
        msg = _make_message(content="see zip", attachments=[att])

        prompt, _ = await build_prompt_and_images(msg)

        assert prompt == "see zip"
        att.read.assert_not_called()

    @pytest.mark.asyncio
    async def test_oversized_attachment_skipped(self) -> None:
        att = _make_attachment(
            filename="huge.txt",
            content_type="text/plain",
            size=MAX_ATTACHMENT_BYTES + 1,
        )
        msg = _make_message(content="big file", attachments=[att])

        prompt, _ = await build_prompt_and_images(msg)

        assert prompt == "big file"
        att.read.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_content_with_attachment(self) -> None:
        """Message with only an attachment (no text) should still work."""
        att = _make_attachment(
            filename="code.py", content_type="text/x-python", content=b"print('hi')"
        )
        msg = _make_message(content="", attachments=[att])

        prompt, _ = await build_prompt_and_images(msg)

        assert "code.py" in prompt
        assert "print('hi')" in prompt

    @pytest.mark.asyncio
    async def test_max_attachments_limit(self) -> None:
        """Only the first MAX_ATTACHMENTS files should be processed."""
        attachments = [
            _make_attachment(filename=f"file{i}.txt", content=f"content{i}".encode())
            for i in range(MAX_ATTACHMENTS + 2)
        ]
        msg = _make_message(attachments=attachments)

        await build_prompt_and_images(msg)

        for att in attachments[MAX_ATTACHMENTS:]:
            att.read.assert_not_called()

    @pytest.mark.asyncio
    async def test_total_size_limit_stops_processing(self) -> None:
        """Processing stops when cumulative size exceeds MAX_TOTAL_BYTES."""
        chunk = MAX_ATTACHMENT_BYTES - 100
        attachments = [
            _make_attachment(
                filename=f"file{i}.txt",
                size=chunk,
                content=b"x" * chunk,
            )
            for i in range(10)
        ]
        msg = _make_message(attachments=attachments)

        await build_prompt_and_images(msg)

        read_count = sum(1 for att in attachments if att.read.called)
        expected_max = (MAX_TOTAL_BYTES // chunk) + 1
        assert read_count <= expected_max

    @pytest.mark.asyncio
    async def test_json_attachment_included(self) -> None:
        """application/json is in the allowed types."""
        att = _make_attachment(
            filename="config.json",
            content_type="application/json",
            content=b'{"key": "value"}',
        )
        msg = _make_message(content="here is config", attachments=[att])

        prompt, _ = await build_prompt_and_images(msg)

        assert "config.json" in prompt
        assert '{"key": "value"}' in prompt

    @pytest.mark.asyncio
    async def test_multiple_text_attachments(self) -> None:
        """Multiple allowed attachments should all be included."""
        attachments = [
            _make_attachment(filename="a.txt", content=b"alpha"),
            _make_attachment(filename="b.md", content_type="text/markdown", content=b"beta"),
        ]
        msg = _make_message(content="two files", attachments=attachments)

        prompt, _ = await build_prompt_and_images(msg)

        assert "a.txt" in prompt
        assert "alpha" in prompt
        assert "b.md" in prompt
        assert "beta" in prompt
