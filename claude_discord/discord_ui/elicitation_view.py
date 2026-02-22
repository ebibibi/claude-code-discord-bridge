"""Discord UI for MCP elicitation requests.

MCP servers can request interactive input from the user via elicitation.
Two modes are supported:

- url-mode: Show a URL button (the user visits the URL and the MCP server
  handles the rest). We inject a "done" response after the button is clicked.

- form-mode: Show a Modal with text inputs derived from the JSON schema.
  We collect the form values and inject them as the response.
"""

from __future__ import annotations

import logging
from typing import Any

import discord

from ..claude.types import ElicitationRequest

logger = logging.getLogger(__name__)

ELICITATION_TIMEOUT = 300  # 5 minutes


class ElicitationUrlView(discord.ui.View):
    """Single button opening a URL for url-mode elicitation."""

    def __init__(self, runner, request: ElicitationRequest) -> None:
        super().__init__(timeout=ELICITATION_TIMEOUT)
        self._runner = runner
        self._request = request
        # Add the URL as a link button (no callback needed — Discord opens it).
        if request.url:
            self.add_item(discord.ui.Button(label="🔗 Open link", url=request.url))
        # "Done" button to confirm the user completed the URL flow.
        self._done_added = False

    @discord.ui.button(label="✅ Done", style=discord.ButtonStyle.success)
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._runner.inject_tool_result(self._request.request_id, {"completed": True})
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)
        logger.info("Elicitation (url-mode) completed (request_id=%s)", self._request.request_id)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._runner.inject_tool_result(self._request.request_id, {"completed": False})
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)

    async def on_timeout(self) -> None:
        await self._runner.inject_tool_result(self._request.request_id, {"completed": False})


def _schema_to_modal_fields(schema: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """Extract (name, description, required) tuples from a JSON schema object.

    Only handles simple flat schemas (object with string properties).
    Returns at most 5 fields (Discord Modal limit).
    """
    properties = schema.get("properties", {})
    required_keys: set[str] = set(schema.get("required", []))
    fields = []
    for key, prop in list(properties.items())[:5]:
        desc = prop.get("description", prop.get("title", key))
        fields.append((key, desc, key in required_keys))
    return fields


class ElicitationFormModal(discord.ui.Modal):
    """Modal for form-mode elicitation. Fields are dynamically generated from JSON schema."""

    def __init__(self, runner, request: ElicitationRequest) -> None:
        title = f"Input required — {request.server_name}"[:45]
        super().__init__(title=title, timeout=ELICITATION_TIMEOUT)
        self._runner = runner
        self._request = request

        # Dynamically add TextInput components from the schema.
        self._field_names: list[str] = []
        for name, desc, required in _schema_to_modal_fields(request.schema):
            self._field_names.append(name)
            self.add_item(
                discord.ui.TextInput(
                    label=name[:45],
                    placeholder=desc[:100] if desc else None,
                    required=required,
                    max_length=1000,
                )
            )

        # Fallback: if schema has no properties, add a single free-form field.
        if not self._field_names:
            self._field_names = ["response"]
            self.add_item(
                discord.ui.TextInput(
                    label="Response",
                    placeholder=request.message[:100] if request.message else "Enter your response",
                    required=True,
                    style=discord.TextStyle.paragraph,
                )
            )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        # Collect field values into a dict.
        values: dict[str, str] = {}
        for child, name in zip(self.children, self._field_names, strict=False):
            if isinstance(child, discord.ui.TextInput):
                values[name] = child.value

        await self._runner.inject_tool_result(self._request.request_id, {"values": values})
        logger.info(
            "Elicitation (form-mode) submitted (request_id=%s, fields=%s)",
            self._request.request_id,
            list(values.keys()),
        )


class ElicitationFormView(discord.ui.View):
    """Single button that opens the form Modal for form-mode elicitation."""

    def __init__(self, runner, request: ElicitationRequest) -> None:
        super().__init__(timeout=ELICITATION_TIMEOUT)
        self._runner = runner
        self._request = request

    @discord.ui.button(label="📝 Fill in form", style=discord.ButtonStyle.primary)
    async def open_form(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        modal = ElicitationFormModal(self._runner, self._request)
        await interaction.response.send_modal(modal)
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        await self._runner.inject_tool_result(self._request.request_id, {"completed": False})
        self.stop()
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)

    async def on_timeout(self) -> None:
        await self._runner.inject_tool_result(self._request.request_id, {"completed": False})
