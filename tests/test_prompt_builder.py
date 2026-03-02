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
    async def test_oversized_attachment_truncated(self) -> None:
        """MAX_ATTACHMENT_BYTES 超のファイルはスキップせず切り詰めて含める。"""
        big_content = b"HEADER" + b"x" * MAX_ATTACHMENT_BYTES
        att = _make_attachment(
            filename="huge.txt",
            content_type="text/plain",
            content=big_content,
            size=len(big_content),
        )
        msg = _make_message(content="big file", attachments=[att])

        prompt, _ = await build_prompt_and_images(msg)

        assert "huge.txt" in prompt
        assert "HEADER" in prompt
        assert "truncated" in prompt.lower()
        att.read.assert_called_once()

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


class TestNoContentType:
    """content_type が None のとき（Discord のロングテキスト自動変換等）の動作。"""

    @pytest.mark.asyncio
    async def test_no_content_type_txt_extension_treated_as_text(self) -> None:
        """Discord がロングテキストを message.txt に自動変換するとき content_type が
        None になる。拡張子 .txt なら text/plain として扱うべき。"""
        att = _make_attachment(
            filename="message.txt",
            content_type=None,
            content=b"This is a long message that Discord converted to a file.",
        )
        att.content_type = None  # content_type を明示的に None に
        msg = _make_message(content="", attachments=[att])

        prompt, image_urls = await build_prompt_and_images(msg)

        assert "message.txt" in prompt
        assert "long message" in prompt
        assert image_urls == []

    @pytest.mark.asyncio
    async def test_no_content_type_py_extension_treated_as_text(self) -> None:
        """コードファイル（.py）も content_type なしでテキストとして読まれるべき。"""
        att = _make_attachment(
            filename="script.py",
            content_type=None,
            content=b"print('hello')",
        )
        att.content_type = None
        msg = _make_message(content="fix this", attachments=[att])

        prompt, _ = await build_prompt_and_images(msg)

        assert "script.py" in prompt
        assert "print('hello')" in prompt

    @pytest.mark.asyncio
    async def test_no_content_type_unknown_extension_skipped(self) -> None:
        """content_type もなく拡張子も不明なら安全のためスキップ。"""
        att = _make_attachment(
            filename="data.bin",
            content_type=None,
            content=b"\x00\x01\x02binary",
        )
        att.content_type = None
        msg = _make_message(content="what is this", attachments=[att])

        prompt, image_urls = await build_prompt_and_images(msg)

        assert "data.bin" not in prompt
        assert image_urls == []

    @pytest.mark.asyncio
    async def test_no_content_type_png_extension_not_sent_as_image(self) -> None:
        """content_type なし＋.png 拡張子でも、CDN URL が image_urls に入るべき。"""
        att = _make_attachment(
            filename="screenshot.png",
            content_type=None,
            url="https://cdn.discordapp.com/attachments/1/2/screenshot.png",
            content=b"",
        )
        att.content_type = None
        msg = _make_message(content="see this", attachments=[att])

        _, image_urls = await build_prompt_and_images(msg)

        assert len(image_urls) == 1
        assert "screenshot.png" in image_urls[0]


class TestLargeTextAttachment:
    """大きいテキスト添付ファイル（Discord ロングテキスト自動変換等）の動作。"""

    @pytest.mark.asyncio
    async def test_large_text_attachment_truncated_not_skipped(self) -> None:
        """107 KB のテキストファイルはスキップではなく切り詰めて含める。"""
        big_content = b"x" * 300_000
        att = _make_attachment(
            filename="message.txt",
            content_type="text/plain",
            content=big_content,
            size=300_000,
        )
        msg = _make_message(content="", attachments=[att])

        prompt, _ = await build_prompt_and_images(msg)

        # スキップされず、ファイル名が含まれる
        assert "message.txt" in prompt
        # 切り詰め通知が入る
        assert "truncated" in prompt.lower() or "省略" in prompt

    @pytest.mark.asyncio
    async def test_large_text_attachment_shows_first_n_bytes(self) -> None:
        """切り詰め時は先頭部分のコンテンツが含まれる。"""
        content = b"START" + b"a" * 200_000 + b"END"
        att = _make_attachment(
            filename="big.txt",
            content_type="text/plain",
            content=content,
            size=len(content),
        )
        msg = _make_message(content="read this", attachments=[att])

        prompt, _ = await build_prompt_and_images(msg)

        assert "big.txt" in prompt
        assert "START" in prompt
        # 末尾の END は切り詰められて含まれない
        assert "END" not in prompt
