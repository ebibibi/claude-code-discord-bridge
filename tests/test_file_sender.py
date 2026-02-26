"""Tests for discord_ui.file_sender.

All tests use tmp_path (pytest built-in) and AsyncMock so they run on every
OS without a real Discord connection.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_discord.discord_ui.file_sender import (
    _is_binary,
    _relative_path,
    collect_discord_files,
    send_files,
)

# ---------------------------------------------------------------------------
# _is_binary
# ---------------------------------------------------------------------------


class TestIsBinary:
    def test_plain_text_is_not_binary(self) -> None:
        assert _is_binary(b"hello world\nprint('hi')\n") is False

    def test_null_byte_flags_binary(self) -> None:
        assert _is_binary(b"data\x00more data") is True

    def test_empty_bytes_are_not_binary(self) -> None:
        assert _is_binary(b"") is False

    def test_null_byte_beyond_first_8kb_not_detected(self) -> None:
        """Only the first 8 KB is sampled — null bytes later are ignored."""
        data = b"a" * 8192 + b"\x00"
        assert _is_binary(data) is False


# ---------------------------------------------------------------------------
# _relative_path
# ---------------------------------------------------------------------------


class TestRelativePath:
    def test_relative_when_inside_working_dir(self) -> None:
        assert _relative_path("/work/src/foo.py", "/work") == "src/foo.py"

    def test_basename_when_outside_working_dir(self) -> None:
        assert _relative_path("/other/foo.py", "/work") == "foo.py"

    def test_basename_when_no_working_dir(self) -> None:
        assert _relative_path("/some/path/foo.py", None) == "foo.py"

    def test_same_dir_returns_filename(self) -> None:
        assert _relative_path("/work/foo.py", "/work") == "foo.py"


# ---------------------------------------------------------------------------
# collect_discord_files
# ---------------------------------------------------------------------------


class TestCollectDiscordFiles:
    def test_text_file_returned_as_discord_file(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.py"
        f.write_text("print('hello')", encoding="utf-8")

        files = collect_discord_files([str(f)], str(tmp_path))

        assert len(files) == 1
        assert files[0].filename == "hello.py"

    def test_relative_display_name_inside_subdir(self, tmp_path: Path) -> None:
        sub = tmp_path / "src"
        sub.mkdir()
        f = sub / "main.py"
        f.write_text("x = 1", encoding="utf-8")

        files = collect_discord_files([str(f)], str(tmp_path))

        assert files[0].filename == "src/main.py"

    def test_missing_file_is_skipped(self, tmp_path: Path) -> None:
        missing = str(tmp_path / "ghost.py")

        files = collect_discord_files([missing], str(tmp_path))

        assert files == []

    def test_oversized_file_is_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "big.txt"
        f.write_bytes(b"x" * 1024)

        files = collect_discord_files([str(f)], str(tmp_path), max_bytes=512)

        assert files == []

    def test_binary_file_is_skipped(self, tmp_path: Path) -> None:
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\x03")

        files = collect_discord_files([str(f)], str(tmp_path))

        assert files == []

    def test_multiple_valid_files_all_returned(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("a = 1", encoding="utf-8")
        (tmp_path / "b.py").write_text("b = 2", encoding="utf-8")

        files = collect_discord_files(
            [str(tmp_path / "a.py"), str(tmp_path / "b.py")],
            str(tmp_path),
        )

        assert len(files) == 2
        names = {f.filename for f in files}
        assert names == {"a.py", "b.py"}

    def test_file_content_readable_from_returned_object(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("result = 42", encoding="utf-8")

        files = collect_discord_files([str(f)], str(tmp_path))

        content = files[0].fp.read()
        assert b"result = 42" in content

    def test_no_working_dir_uses_basename(self, tmp_path: Path) -> None:
        f = tmp_path / "foo.py"
        f.write_text("x = 1", encoding="utf-8")

        files = collect_discord_files([str(f)], None)

        assert files[0].filename == "foo.py"


# ---------------------------------------------------------------------------
# send_files
# ---------------------------------------------------------------------------


class TestSendFiles:
    @pytest.mark.asyncio
    async def test_does_nothing_for_empty_list(self) -> None:
        thread = MagicMock()
        thread.send = AsyncMock()

        await send_files(thread, [], None)

        thread.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_file_attachment(self, tmp_path: Path) -> None:
        thread = MagicMock()
        thread.send = AsyncMock()
        f = tmp_path / "result.py"
        f.write_text("print('done')", encoding="utf-8")

        await send_files(thread, [str(f)], str(tmp_path))

        thread.send.assert_called_once()
        kwargs = thread.send.call_args.kwargs
        assert "files" in kwargs
        assert len(kwargs["files"]) == 1

    @pytest.mark.asyncio
    async def test_discord_error_does_not_propagate(self, tmp_path: Path) -> None:
        """A Discord API failure must not crash the session."""
        thread = MagicMock()
        thread.send = AsyncMock(side_effect=Exception("connection reset"))
        f = tmp_path / "foo.py"
        f.write_text("x = 1", encoding="utf-8")

        # Must complete without raising
        await send_files(thread, [str(f)], str(tmp_path))

    @pytest.mark.asyncio
    async def test_batches_more_than_10_files(self, tmp_path: Path) -> None:
        """Discord allows max 10 files per message; extras go in a second send."""
        thread = MagicMock()
        thread.send = AsyncMock()

        paths = []
        for i in range(12):
            f = tmp_path / f"file{i}.py"
            f.write_text(f"x = {i}", encoding="utf-8")
            paths.append(str(f))

        await send_files(thread, paths, str(tmp_path))

        # 12 files → 2 calls (10 + 2)
        assert thread.send.call_count == 2
        first_batch = thread.send.call_args_list[0].kwargs["files"]
        second_batch = thread.send.call_args_list[1].kwargs["files"]
        assert len(first_batch) == 10
        assert len(second_batch) == 2

    @pytest.mark.asyncio
    async def test_skips_all_binary_files_sends_nothing(self, tmp_path: Path) -> None:
        thread = MagicMock()
        thread.send = AsyncMock()
        f = tmp_path / "img.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")

        await send_files(thread, [str(f)], str(tmp_path))

        thread.send.assert_not_called()
