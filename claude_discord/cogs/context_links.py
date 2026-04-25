"""ContextLinksCog — post project-relevant links when a thread is created.

Reads an optional JSON config that maps project keywords to external
resource links (Obsidian notes, GitHub repos, documentation, etc.).
When a new Discord thread matches a configured project, the Cog posts
a compact embed with the relevant links.

Zero-config: if no config file exists, the Cog does nothing.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import discord
from discord.ext import commands

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

COLOR_CONTEXT = 0x95A5A6


def build_obsidian_uri(vault: str, file_path: str) -> str:
    """Build an ``obsidian://open`` URI from a vault name and file path."""
    return f"obsidian://open?vault={quote(vault, safe='')}&file={quote(file_path, safe='')}"


def load_config(path: str) -> dict[str, Any] | None:
    """Load and validate a context-links JSON config file.

    Returns ``None`` when the file is missing, malformed, or has no projects.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None
    projects = data.get("projects")
    if not isinstance(projects, list) or len(projects) == 0:
        return None
    return data


def match_project(
    thread_name: str,
    config: dict[str, Any],
) -> list[dict[str, str]] | None:
    """Return resolved links for the first project whose keywords match *thread_name*.

    Matching is case-insensitive substring search.  Returns ``None`` when no
    project matches.  Each returned link dict includes a ``_resolved`` key with
    the final URL string.
    """
    if not thread_name:
        return None

    name_lower = thread_name.lower()
    vault = config.get("obsidian_vault", "")

    for project in config.get("projects", []):
        keywords: list[str] = project.get("match", [])
        if any(kw.lower() in name_lower for kw in keywords):
            resolved: list[dict[str, str]] = []
            for link in project.get("links", []):
                entry = dict(link)
                if "obsidian" in link:
                    entry["_resolved"] = build_obsidian_uri(vault, link["obsidian"])
                elif "url" in link:
                    entry["_resolved"] = link["url"]
                else:
                    continue
                resolved.append(entry)
            return resolved if resolved else None
    return None


def build_context_embed(links: list[dict[str, str]]) -> discord.Embed:
    """Build a compact Discord embed listing context links."""
    lines: list[str] = []
    for link in links:
        label = link.get("label", "Link")
        url = link.get("_resolved", "")
        if url.startswith(("http://", "https://")):
            lines.append(f"{label} — {url}")
        else:
            lines.append(f"{label} — `{url}`")

    return discord.Embed(
        title="\U0001f4ce Context Links",
        description="\n".join(lines),
        color=COLOR_CONTEXT,
    )


class ContextLinksCog(commands.Cog):
    """Posts project-relevant resource links when a matching thread is created."""

    def __init__(
        self,
        bot: commands.Bot,
        *,
        config_path: str | None = None,
        channel_ids: set[int] | None = None,
    ) -> None:
        self.bot = bot
        self._channel_ids = channel_ids
        self._config = load_config(config_path or "")

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        if self._config is None:
            return
        if self._channel_ids is not None and thread.parent_id not in self._channel_ids:
            return

        links = match_project(thread.name, self._config)
        if links is None:
            return

        embed = build_context_embed(links)
        with contextlib.suppress(discord.HTTPException):
            await thread.send(embed=embed)
