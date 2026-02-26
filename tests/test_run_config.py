"""Tests for RunConfig validation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from claude_discord.cogs.run_config import RunConfig


def _make_config(**overrides):
    """Create a RunConfig with minimal required fields."""
    defaults = {
        "thread": MagicMock(),
        "runner": MagicMock(),
        "prompt": "hello",
    }
    defaults.update(overrides)
    return RunConfig(**defaults)


class TestRunConfigValidation:
    """Test RunConfig.__post_init__ validation."""

    def test_empty_prompt_no_images_raises(self):
        """Empty prompt without images should raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            _make_config(prompt="")

    def test_empty_prompt_with_images_allowed(self):
        """Empty prompt with image_urls should be accepted."""
        config = _make_config(prompt="", image_urls=["https://cdn.example.com/img.png"])
        assert config.prompt == ""
        assert config.image_urls == ["https://cdn.example.com/img.png"]

    def test_nonempty_prompt_no_images_allowed(self):
        """Normal text prompt should work as before."""
        config = _make_config(prompt="hello")
        assert config.prompt == "hello"

    def test_nonempty_prompt_with_images_allowed(self):
        """Text prompt with images should work."""
        config = _make_config(prompt="describe this", image_urls=["https://example.com/a.png"])
        assert config.prompt == "describe this"

    def test_empty_prompt_empty_images_raises(self):
        """Empty prompt with empty image list should raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            _make_config(prompt="", image_urls=[])

    def test_with_prompt_preserves_images(self):
        """with_prompt should carry over image_urls."""
        original = _make_config(prompt="old", image_urls=["https://example.com/img.png"])
        updated = original.with_prompt("new prompt")
        assert updated.prompt == "new prompt"
        assert updated.image_urls == ["https://example.com/img.png"]
