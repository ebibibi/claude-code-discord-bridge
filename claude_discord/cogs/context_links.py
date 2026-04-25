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
import os
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


def build_obsidian_redirect_url(base_url: str, vault: str, file_path: str) -> str:
    """Build an HTTPS redirect URL that 302s to ``obsidian://open``.

    Requires the ccdb API server (or any HTTP server) to serve a redirect
    at ``/open/obsidian``.
    """
    base = base_url.rstrip("/")
    return f"{base}/open/obsidian?vault={quote(vault, safe='')}&file={quote(file_path, safe='')}"


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
    *,
    public_api_url: str | None = None,
) -> list[dict[str, str]] | None:
    """Return resolved links for the first project whose keywords match *thread_name*.

    Matching is case-insensitive substring search.  Returns ``None`` when no
    project matches.  Each returned link dict includes a ``_resolved`` key with
    the final URL string.

    When *public_api_url* is set, obsidian links resolve to an HTTPS redirect
    URL (clickable in Discord buttons).  Otherwise they use ``obsidian://``.
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
                    if public_api_url:
                        entry["_resolved"] = build_obsidian_redirect_url(
                            public_api_url, vault, link["obsidian"]
                        )
                    else:
                        entry["_resolved"] = build_obsidian_uri(vault, link["obsidian"])
                elif "url" in link:
                    entry["_resolved"] = link["url"]
                else:
                    continue
                resolved.append(entry)
            return resolved if resolved else None
    return None


def build_context_embed(links: list[dict[str, str]]) -> discord.Embed:
    """Build a Discord embed for links that cannot be rendered as buttons.

    Links with HTTPS ``_resolved`` URLs are excluded — they go into
    ``build_link_view`` as proper Discord link buttons instead.  Only
    non-HTTPS links (e.g. ``obsidian://``) appear here as readable text.
    """
    lines: list[str] = []
    for link in links:
        url = link.get("_resolved", "")
        if url.startswith(("http://", "https://")):
            continue
        label = link.get("label", "Link")
        if "obsidian" in link:
            lines.append(f"{label} — `{link['obsidian']}`")
        else:
            lines.append(f"{label} — `{url}`")

    return discord.Embed(
        title="\U0001f4ce Context Links",
        description="\n".join(lines) or None,
        color=COLOR_CONTEXT,
    )


def build_link_view(links: list[dict[str, str]]) -> discord.ui.View | None:
    """Build a ``discord.ui.View`` with link buttons for HTTPS URLs.

    Returns ``None`` when there are no HTTPS links.
    """
    view = discord.ui.View()
    count = 0
    for link in links:
        url = link.get("_resolved", "")
        if not url.startswith(("http://", "https://")):
            continue
        label = link.get("label", "Link")
        view.add_item(discord.ui.Button(style=discord.ButtonStyle.link, label=label, url=url))
        count += 1
    return view if count > 0 else None


class ContextLinksCog(commands.Cog):
    """Posts project-relevant resource links when a matching thread is created."""

    def __init__(
        self,
        bot: commands.Bot,
        *,
        config_path: str | None = None,
        channel_ids: set[int] | None = None,
        public_api_url: str | None = None,
    ) -> None:
        self.bot = bot
        self._channel_ids = channel_ids
        self._config = load_config(config_path or "")
        self._public_api_url = public_api_url or os.getenv("CCDB_PUBLIC_API_URL")

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        logger.debug(
            "on_thread_create fired: name=%r parent_id=%s channel_ids=%s config=%s",
            thread.name,
            thread.parent_id,
            self._channel_ids,
            self._config is not None,
        )
        if self._config is None:
            return
        if self._channel_ids is not None and thread.parent_id not in self._channel_ids:
            return

        links = match_project(thread.name, self._config, public_api_url=self._public_api_url)
        if links is None:
            return

        logger.info("Context links matched for thread %r: %d link(s)", thread.name, len(links))
        embed = build_context_embed(links)
        view = build_link_view(links)
        with contextlib.suppress(discord.HTTPException):
            await thread.send(embed=embed, view=view or discord.utils.MISSING)
