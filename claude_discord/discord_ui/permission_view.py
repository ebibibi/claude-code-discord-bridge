"""Discord UI for tool permission requests.

When Claude needs to execute a tool in a non-permissive mode, it emits a
permission_request system event. This module provides the View with
Allow / Deny buttons and injects the response via runner.inject_tool_result().
"""

from __future__ import annotations

import logging

import discord

from ..claude.types import PermissionRequest

logger = logging.getLogger(__name__)

PERMISSION_TIMEOUT = 120  # 2 minutes to approve/deny


class PermissionView(discord.ui.View):
    """Allow / Deny buttons for tool permission requests."""

    def __init__(self, runner, request: PermissionRequest) -> None:
        super().__init__(timeout=PERMISSION_TIMEOUT)
        self._runner = runner
        self._request = request

    @discord.ui.button(label="✅ Allow", style=discord.ButtonStyle.success)
    async def allow(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._runner.inject_tool_result(self._request.request_id, {"approved": True})
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)
        logger.info(
            "Permission allowed: %s (request_id=%s)",
            self._request.tool_name,
            self._request.request_id,
        )

    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._runner.inject_tool_result(self._request.request_id, {"approved": False})
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)
        logger.info(
            "Permission denied: %s (request_id=%s)",
            self._request.tool_name,
            self._request.request_id,
        )

    async def on_timeout(self) -> None:
        """Auto-deny if no response within timeout."""
        await self._runner.inject_tool_result(self._request.request_id, {"approved": False})
        logger.info("Permission request timed out (request_id=%s)", self._request.request_id)
