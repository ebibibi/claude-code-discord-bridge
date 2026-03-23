"""Tests for prompt_builder module: attachment handling and prompt construction."""

from __future__ import annotations

import base64
import io
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from PIL import Image

from claude_discord.cogs.prompt_builder import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS,
    MAX_TOTAL_BYTES,
    _convert_image_if_needed,
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
    async def test_image_attachment_returns_base64_data(self) -> None:
        """Images are downloaded and returned as base64-encoded ImageData."""
        image_bytes = b"\x89PNG\r\n\x1a\nfake-png-data"
        att = _make_attachment(
            filename="image.png",
            content_type="image/png",
            size=len(image_bytes),
            content=image_bytes,
        )
        msg = _make_message(content="see image", attachments=[att])

        prompt, images = await build_prompt_and_images(msg)

        assert prompt == "see image"
        assert len(images) == 1
        assert images[0].media_type == "image/png"
        assert images[0].data == base64.standard_b64encode(image_bytes).decode("ascii")
        att.read.assert_called_once()

    @pytest.mark.asyncio
    async def test_jpeg_image_media_type(self) -> None:
        """JPEG images get the correct media_type."""
        jpeg_bytes = b"\xff\xd8\xff\xe0fake-jpeg"
        att = _make_attachment(
            filename="photo.jpg",
            content_type="image/jpeg",
            size=len(jpeg_bytes),
            content=jpeg_bytes,
        )
        msg = _make_message(content="", attachments=[att])

        _, images = await build_prompt_and_images(msg)

        assert len(images) == 1
        assert images[0].media_type == "image/jpeg"

    @pytest.mark.asyncio
    async def test_webp_image_media_type(self) -> None:
        """WebP images get the correct media_type."""
        att = _make_attachment(
            filename="pic.webp",
            content_type="image/webp",
            size=100,
            content=b"webp-data",
        )
        msg = _make_message(content="", attachments=[att])

        _, images = await build_prompt_and_images(msg)

        assert len(images) == 1
        assert images[0].media_type == "image/webp"

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

    @pytest.mark.asyncio
    async def test_image_download_failure_skipped(self) -> None:
        """If image download fails, it's silently skipped."""
        att = _make_attachment(
            filename="broken.png",
            content_type="image/png",
            size=100,
        )
        att.read = AsyncMock(side_effect=Exception("download failed"))
        msg = _make_message(content="see this", attachments=[att])

        prompt, images = await build_prompt_and_images(msg)

        assert prompt == "see this"
        assert images == []


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

        prompt, images = await build_prompt_and_images(msg)

        assert "message.txt" in prompt
        assert "long message" in prompt
        assert images == []

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

        prompt, images = await build_prompt_and_images(msg)

        assert "data.bin" not in prompt
        assert images == []

    @pytest.mark.asyncio
    async def test_no_content_type_png_extension_downloaded_as_image(self) -> None:
        """content_type なし＋.png 拡張子 → ダウンロードして base64 ImageData に。"""
        image_bytes = b"\x89PNGfakedata"
        att = _make_attachment(
            filename="screenshot.png",
            content_type=None,
            content=image_bytes,
        )
        att.content_type = None
        msg = _make_message(content="see this", attachments=[att])

        _, images = await build_prompt_and_images(msg)

        assert len(images) == 1
        assert images[0].media_type == "image/png"
        assert images[0].data == base64.standard_b64encode(image_bytes).decode("ascii")


class TestConvertImageIfNeeded:
    """Tests for _convert_image_if_needed — automatic format conversion."""

    def _make_bmp_bytes(self, mode: str = "RGB", size: tuple[int, int] = (2, 2)) -> bytes:
        """Create a real BMP image in memory."""
        img = Image.new(mode, size, color="red")
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        return buf.getvalue()

    def _make_tiff_bytes(self, mode: str = "RGB") -> bytes:
        """Create a real TIFF image in memory."""
        img = Image.new(mode, (2, 2), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="TIFF")
        return buf.getvalue()

    def test_supported_format_returned_as_is(self) -> None:
        """JPEG/PNG/GIF/WebP are returned without conversion."""
        raw = b"fake-jpeg-data"
        result_bytes, result_type = _convert_image_if_needed(raw, "image/jpeg")
        assert result_bytes is raw
        assert result_type == "image/jpeg"

    def test_png_returned_as_is(self) -> None:
        raw = b"fake-png-data"
        result_bytes, result_type = _convert_image_if_needed(raw, "image/png")
        assert result_bytes is raw
        assert result_type == "image/png"

    def test_bmp_converted_to_jpeg(self) -> None:
        """BMP (opaque) should be converted to JPEG."""
        bmp_bytes = self._make_bmp_bytes("RGB")
        result_bytes, result_type = _convert_image_if_needed(bmp_bytes, "image/bmp")
        assert result_type == "image/jpeg"
        assert result_bytes != bmp_bytes
        # Verify it's a valid JPEG
        img = Image.open(io.BytesIO(result_bytes))
        assert img.format == "JPEG"

    def test_bmp_rgba_converted_to_png(self) -> None:
        """BMP with alpha should be converted to PNG to preserve transparency."""
        img = Image.new("RGBA", (2, 2), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")  # BMP doesn't support RGBA natively
        rgba_bytes = buf.getvalue()
        # Use a PNG with RGBA as input but pretend it's unsupported type
        result_bytes, result_type = _convert_image_if_needed(rgba_bytes, "image/x-test")
        assert result_type == "image/png"

    def test_tiff_converted_to_jpeg(self) -> None:
        """TIFF should be converted to JPEG."""
        tiff_bytes = self._make_tiff_bytes("RGB")
        result_bytes, result_type = _convert_image_if_needed(tiff_bytes, "image/tiff")
        assert result_type == "image/jpeg"
        img = Image.open(io.BytesIO(result_bytes))
        assert img.format == "JPEG"

    def test_pillow_not_installed_fallback(self) -> None:
        """Without Pillow, returns raw bytes with image/png fallback."""
        raw = b"some-data"
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            # Force re-import failure by patching builtins
            original_import = (
                __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
            )

            def mock_import(name, *args, **kwargs):
                if name == "PIL" or name == "PIL.Image":
                    raise ImportError("No module named 'PIL'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result_bytes, result_type = _convert_image_if_needed(raw, "image/bmp")
                assert result_bytes is raw
                assert result_type == "image/png"

    def test_corrupt_image_fallback(self) -> None:
        """Corrupt image data falls back gracefully."""
        raw = b"not-a-valid-image"
        result_bytes, result_type = _convert_image_if_needed(raw, "image/bmp")
        assert result_bytes is raw
        assert result_type == "image/png"


class TestBmpImageConversionIntegration:
    """Integration test: BMP attachment → converted JPEG ImageData."""

    @pytest.mark.asyncio
    async def test_bmp_attachment_converted_to_jpeg(self) -> None:
        """BMP image attached in Discord should be auto-converted to JPEG."""
        img = Image.new("RGB", (4, 4), color="green")
        buf = io.BytesIO()
        img.save(buf, format="BMP")
        bmp_bytes = buf.getvalue()

        att = _make_attachment(
            filename="photo.bmp",
            content_type="image/bmp",
            size=len(bmp_bytes),
            content=bmp_bytes,
        )
        msg = _make_message(content="look at this", attachments=[att])

        _, images = await build_prompt_and_images(msg)

        assert len(images) == 1
        assert images[0].media_type == "image/jpeg"
        # Verify the base64 decodes to valid JPEG
        decoded = base64.standard_b64decode(images[0].data)
        result_img = Image.open(io.BytesIO(decoded))
        assert result_img.format == "JPEG"

    @pytest.mark.asyncio
    async def test_tiff_attachment_converted_to_jpeg(self) -> None:
        """TIFF image should be auto-converted to JPEG."""
        img = Image.new("RGB", (4, 4), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="TIFF")
        tiff_bytes = buf.getvalue()

        att = _make_attachment(
            filename="scan.tiff",
            content_type="image/tiff",
            size=len(tiff_bytes),
            content=tiff_bytes,
        )
        msg = _make_message(content="", attachments=[att])

        _, images = await build_prompt_and_images(msg)

        assert len(images) == 1
        assert images[0].media_type == "image/jpeg"

    @pytest.mark.asyncio
    async def test_supported_format_not_converted(self) -> None:
        """PNG/JPEG/GIF/WebP should pass through without conversion."""
        png_bytes = b"\x89PNG\r\n\x1a\nfake"
        att = _make_attachment(
            filename="pic.png",
            content_type="image/png",
            size=len(png_bytes),
            content=png_bytes,
        )
        msg = _make_message(content="", attachments=[att])

        _, images = await build_prompt_and_images(msg)

        assert len(images) == 1
        assert images[0].media_type == "image/png"
        assert images[0].data == base64.standard_b64encode(png_bytes).decode("ascii")


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


class TestSaveAttachmentsToDisk:
    """save_dir が指定されたとき、全添付ファイルがディスクに保存される。"""

    @pytest.mark.asyncio
    async def test_text_attachment_saved_to_disk(self) -> None:
        """テキスト添付はディスクに保存され、パスがプロンプトヘッダーに含まれる。"""
        att = _make_attachment(filename="notes.txt", content=b"file content here")
        msg = _make_message(content="check this", attachments=[att])

        with tempfile.TemporaryDirectory() as save_dir:
            prompt, _ = await build_prompt_and_images(msg, save_dir=save_dir)

            # ファイルがディスクに保存されている
            saved_path = os.path.join(save_dir, "notes.txt")
            assert os.path.exists(saved_path)
            with open(saved_path, "rb") as f:
                assert f.read() == b"file content here"

            # プロンプトにヘッダーが含まれる
            assert "notes.txt" in prompt
            assert saved_path in prompt

    @pytest.mark.asyncio
    async def test_image_saved_to_disk(self) -> None:
        """画像添付もディスクに保存される。"""
        image_bytes = b"\x89PNG\r\n\x1a\nfake-png-data"
        att = _make_attachment(
            filename="screenshot.png",
            content_type="image/png",
            size=len(image_bytes),
            content=image_bytes,
        )
        msg = _make_message(content="see image", attachments=[att])

        with tempfile.TemporaryDirectory() as save_dir:
            prompt, images = await build_prompt_and_images(msg, save_dir=save_dir)

            # ディスクに保存されている
            saved_path = os.path.join(save_dir, "screenshot.png")
            assert os.path.exists(saved_path)

            # base64エンコードも返される（既存動作を維持）
            assert len(images) == 1

            # ヘッダーにパスが含まれる
            assert saved_path in prompt

    @pytest.mark.asyncio
    async def test_pdf_saved_to_disk(self) -> None:
        """PDFなど非テキスト・非画像ファイルもディスクに保存される。"""
        pdf_content = b"%PDF-1.4 fake pdf content"
        att = _make_attachment(
            filename="report.pdf",
            content_type="application/pdf",
            size=len(pdf_content),
            content=pdf_content,
        )
        msg = _make_message(content="see report", attachments=[att])

        with tempfile.TemporaryDirectory() as save_dir:
            prompt, _ = await build_prompt_and_images(msg, save_dir=save_dir)

            # ディスクに保存されている
            saved_path = os.path.join(save_dir, "report.pdf")
            assert os.path.exists(saved_path)
            with open(saved_path, "rb") as f:
                assert f.read() == pdf_content

            # ヘッダーにパスが含まれる
            assert saved_path in prompt
            assert "report.pdf" in prompt

    @pytest.mark.asyncio
    async def test_excel_saved_to_disk(self) -> None:
        """Excelファイルもディスクに保存される。"""
        xlsx_content = b"PK\x03\x04fake xlsx"
        att = _make_attachment(
            filename="data.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size=len(xlsx_content),
            content=xlsx_content,
        )
        msg = _make_message(content="see data", attachments=[att])

        with tempfile.TemporaryDirectory() as save_dir:
            prompt, _ = await build_prompt_and_images(msg, save_dir=save_dir)

            saved_path = os.path.join(save_dir, "data.xlsx")
            assert os.path.exists(saved_path)
            assert saved_path in prompt

    @pytest.mark.asyncio
    async def test_zip_saved_to_disk(self) -> None:
        """ZIPファイルもディスクに保存される（以前はサイレントスキップだった）。"""
        zip_content = b"PK\x03\x04fake zip"
        att = _make_attachment(
            filename="archive.zip",
            content_type="application/zip",
            size=len(zip_content),
            content=zip_content,
        )
        msg = _make_message(content="see zip", attachments=[att])

        with tempfile.TemporaryDirectory() as save_dir:
            prompt, _ = await build_prompt_and_images(msg, save_dir=save_dir)

            saved_path = os.path.join(save_dir, "archive.zip")
            assert os.path.exists(saved_path)
            assert saved_path in prompt

    @pytest.mark.asyncio
    async def test_header_lists_all_files(self) -> None:
        """複数の添付ファイルのヘッダーがまとめて表示される。"""
        attachments = [
            _make_attachment(filename="a.txt", content=b"alpha"),
            _make_attachment(
                filename="b.pdf",
                content_type="application/pdf",
                content=b"%PDF",
            ),
        ]
        msg = _make_message(content="two files", attachments=attachments)

        with tempfile.TemporaryDirectory() as save_dir:
            prompt, _ = await build_prompt_and_images(msg, save_dir=save_dir)

            assert "a.txt" in prompt
            assert "b.pdf" in prompt
            # ヘッダーセクションが存在する
            assert "Attached" in prompt or "添付" in prompt

    @pytest.mark.asyncio
    async def test_no_save_dir_keeps_old_behavior(self) -> None:
        """save_dir=None（デフォルト）のとき、既存の動作が維持される。"""
        att = _make_attachment(
            filename="archive.zip",
            content_type="application/zip",
            content=b"PK...",
        )
        msg = _make_message(content="see zip", attachments=[att])

        # save_dir なし → 従来通りzipはスキップ
        prompt, _ = await build_prompt_and_images(msg)
        assert prompt == "see zip"

    @pytest.mark.asyncio
    async def test_duplicate_filenames_handled(self) -> None:
        """同名ファイルが複数あっても衝突しない。"""
        attachments = [
            _make_attachment(filename="file.txt", content=b"first"),
            _make_attachment(filename="file.txt", content=b"second"),
        ]
        msg = _make_message(content="dupes", attachments=attachments)

        with tempfile.TemporaryDirectory() as save_dir:
            prompt, _ = await build_prompt_and_images(msg, save_dir=save_dir)

            # 両方のファイルが存在する（リネームされている）
            files = os.listdir(save_dir)
            assert len(files) == 2

    @pytest.mark.asyncio
    async def test_header_appears_before_user_message(self) -> None:
        """ヘッダーはユーザーメッセージの前に表示される。"""
        att = _make_attachment(filename="data.csv", content=b"a,b,c")
        msg = _make_message(content="analyze this", attachments=[att])

        with tempfile.TemporaryDirectory() as save_dir:
            prompt, _ = await build_prompt_and_images(msg, save_dir=save_dir)

            header_pos = prompt.find("data.csv")
            message_pos = prompt.find("analyze this")
            # ヘッダーがユーザーメッセージより先に出現する
            assert header_pos < message_pos
