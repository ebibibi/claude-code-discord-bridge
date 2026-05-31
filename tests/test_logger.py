"""Tests for claude_discord.utils.logger.setup_logging()."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch


def _cleanup_handlers(root: logging.Logger, before: list[logging.Handler]) -> None:
    for h in list(root.handlers):
        if h not in before:
            h.close()
            root.removeHandler(h)


class TestSetupLogging:
    def setup_method(self) -> None:
        self._root = logging.getLogger()
        self._handlers_before = list(self._root.handlers)

    def teardown_method(self) -> None:
        _cleanup_handlers(self._root, self._handlers_before)

    def test_default_adds_stream_handler(self) -> None:
        """Without CCDB_LOG_FILE, only a StreamHandler is added."""
        with patch.dict("os.environ", {}, clear=True):
            from claude_discord.utils.logger import setup_logging

            setup_logging()

        new_handlers = [h for h in self._root.handlers if h not in self._handlers_before]
        assert any(isinstance(h, logging.StreamHandler) for h in new_handlers)
        assert not any(isinstance(h, RotatingFileHandler) for h in new_handlers)

    def test_file_handler_added_when_env_set(self, tmp_path: Path) -> None:
        """CCDB_LOG_FILE causes a RotatingFileHandler to be added."""
        log_file = tmp_path / "discord-bot.log"

        with patch.dict("os.environ", {"CCDB_LOG_FILE": str(log_file)}):
            from claude_discord.utils.logger import setup_logging

            setup_logging()

        new_handlers = [h for h in self._root.handlers if h not in self._handlers_before]
        file_handlers = [h for h in new_handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename) == log_file  # type: ignore[attr-defined]

    def test_log_dir_created_automatically(self, tmp_path: Path) -> None:
        """Parent directories of CCDB_LOG_FILE are created automatically."""
        log_file = tmp_path / "logs" / "subdir" / "discord-bot.log"
        assert not log_file.parent.exists()

        with patch.dict("os.environ", {"CCDB_LOG_FILE": str(log_file)}):
            from claude_discord.utils.logger import setup_logging

            setup_logging()

        assert log_file.parent.exists()

    def test_file_handler_rotation_config(self, tmp_path: Path) -> None:
        """RotatingFileHandler is configured with 10MB max and 5 backups."""
        log_file = tmp_path / "discord-bot.log"

        with patch.dict("os.environ", {"CCDB_LOG_FILE": str(log_file)}):
            from claude_discord.utils.logger import setup_logging

            setup_logging()

        new_handlers = [h for h in self._root.handlers if h not in self._handlers_before]
        fh = next(h for h in new_handlers if isinstance(h, RotatingFileHandler))
        assert fh.maxBytes == 10 * 1024 * 1024
        assert fh.backupCount == 5
