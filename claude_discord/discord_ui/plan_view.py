"""Discord UI for Plan Mode approval (ExitPlanMode).

When Claude calls ExitPlanMode, it has finished planning and waits for the
user to approve (execute the plan) or cancel. This module provides the View
with Approve / Cancel buttons and injects the response via runner.inject_tool_result().
"""

from __future__ import annotations

import logging

import discord

logger = logging.getLogger(__name__)

# Timeout for plan approval — if no response in 5 minutes, cancel.
PLAN_APPROVAL_TIMEOUT = 300


class PlanApprovalView(discord.ui.View):
    """Two-button view: ✅ Approve | ❌ Cancel for plan mode."""

    def __init__(self, runner, request_id: str) -> None:
        super().__init__(timeout=PLAN_APPROVAL_TIMEOUT)
        self._runner = runner
        self._request_id = request_id

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._runner.inject_tool_result(self._request_id, {"approved": True})
        self.stop()
        # Disable buttons so they can't be clicked again
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)
        logger.info("Plan approved (request_id=%s)", self._request_id)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._runner.inject_tool_result(self._request_id, {"approved": False})
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)
        logger.info("Plan cancelled (request_id=%s)", self._request_id)

    async def on_timeout(self) -> None:
        """Auto-cancel if no response within timeout."""
        await self._runner.inject_tool_result(self._request_id, {"approved": False})
        logger.info("Plan approval timed out (request_id=%s)", self._request_id)
