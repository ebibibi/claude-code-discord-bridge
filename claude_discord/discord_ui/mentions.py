"""Helpers for Discord mention payloads."""

from __future__ import annotations

from typing import Any

import discord


def user_mention_kwargs(user_id: int | None) -> dict[str, Any]:
    """Return send() kwargs that notify a specific user, or no kwargs if unset."""
    if user_id is None:
        return {}
    return {
        "content": f"<@{user_id}>",
        "allowed_mentions": discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        ),
    }
