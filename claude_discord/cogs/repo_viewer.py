"""Repository viewer Cog.

Provides slash commands for viewing recent git changes in a repository
directly from Discord — no need to open GitHub.

Commands:
- /recent: Show recent commits and changed files
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default repository path (ec-automation-system)
_DEFAULT_REPO = os.getenv(
    "REPO_VIEWER_DEFAULT_PATH",
    "/home/ubuntu/ec-automation-system",
)

COLOR_COMMIT = 0x2ECC71  # Emerald green


async def _run_git(repo_path: str, *args: str) -> str:
    """Run a git command asynchronously and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        repo_path,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode("utf-8", errors="replace").strip()


def _build_recent_embed(
    commits: list[dict[str, str]],
    repo_name: str,
    count: int,
) -> discord.Embed:
    """Build a Discord embed showing recent commits with changed files."""
    title = (
        f"\U0001f4cb {repo_name}"
        f" \u2014 \u6700\u8fd1\u306e\u5909\u66f4\uff08{len(commits)}\u4ef6\uff09"
    )
    embed = discord.Embed(title=title, color=COLOR_COMMIT)

    for commit in commits[:count]:
        # Header: time + message
        time_str = commit.get("time", "")
        msg = commit.get("message", "(no message)")
        sha_short = commit.get("sha", "")[:7]
        author = commit.get("author", "")

        # Changed files
        files_raw = commit.get("files", "")
        file_lines: list[str] = []
        for line in files_raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Format: "M\tfilename" or "A\tfilename"
            parts = line.split("\t", 1)
            if len(parts) == 2:
                status_code, filepath = parts
                icon = {"M": "\u270f\ufe0f", "A": "\U0001f195", "D": "\U0001f5d1\ufe0f"}.get(
                    status_code, "\U0001f4c4"
                )
                file_lines.append(f"{icon} `{filepath}`")
            else:
                file_lines.append(f"\U0001f4c4 `{line}`")

        files_display = "\n".join(file_lines[:8])
        remaining = len(file_lines) - 8
        if remaining > 0:
            files_display += f"\n... +{remaining}\u30d5\u30a1\u30a4\u30eb"

        # Build field value
        header = f"by {author} | `{sha_short}`"
        value = f"{header}\n{files_display}" if files_display else header

        # Truncate field value to Discord limit (1024)
        if len(value) > 1024:
            value = value[:1020] + "..."

        field_name = f"\U0001f552 {time_str} \u2014 {msg}"
        if len(field_name) > 256:
            field_name = field_name[:253] + "..."

        embed.add_field(name=field_name, value=value, inline=False)

    return embed


async def _get_recent_commits(repo_path: str, count: int = 5) -> list[dict[str, str]]:
    """Fetch recent commits with metadata and changed files."""
    # Get commit list: hash, relative time, subject, author
    log_output = await _run_git(
        repo_path,
        "log",
        f"-{count}",
        "--format=%H\x1f%ar\x1f%s\x1f%an",
    )
    if not log_output:
        return []

    commits: list[dict[str, str]] = []
    for line in log_output.split("\n"):
        parts = line.split("\x1f")
        if len(parts) < 4:
            continue
        sha, time_rel, message, author = parts[0], parts[1], parts[2], parts[3]

        # Get changed files for this commit
        files_output = await _run_git(
            repo_path,
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            sha,
        )

        commits.append(
            {
                "sha": sha,
                "time": time_rel,
                "message": message,
                "author": author,
                "files": files_output,
            }
        )

    return commits


class RepoViewerCog(commands.Cog):
    """Cog for viewing repository state from Discord."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="recent",
        description="\u6700\u8fd1\u306egit\u5909\u66f4\u5c65\u6b74\u3092\u8868\u793a",
    )
    @app_commands.describe(
        count="\u8868\u793a\u3059\u308bcommit\u6570\uff08\u30c7\u30d5\u30a9\u30eb\u30c8: 5\uff09",
    )
    async def recent(
        self,
        interaction: discord.Interaction,
        count: int = 5,
    ) -> None:
        """Show recent git commits with changed files."""
        count = max(1, min(10, count))
        await interaction.response.defer()

        try:
            commits = await _get_recent_commits(_DEFAULT_REPO, count)
        except Exception:
            logger.exception("Failed to fetch recent commits")
            await interaction.followup.send(
                "\u274c git\u5c65\u6b74\u306e\u53d6\u5f97\u306b\u5931\u6557",
                ephemeral=True,
            )
            return

        if not commits:
            await interaction.followup.send(
                "\u2139\ufe0f commit\u304c\u898b\u3064\u304b\u308a\u307e\u305b\u3093",
                ephemeral=True,
            )
            return

        repo_name = os.path.basename(_DEFAULT_REPO)
        embed = _build_recent_embed(commits, repo_name, count)

        # Add GitHub link as footer
        github_url = await _run_git(_DEFAULT_REPO, "remote", "get-url", "origin")
        if "github.com" in github_url:
            # Clean up URL (remove .git suffix and credentials)
            clean_url = github_url.replace(".git", "")
            # Remove credentials from URL if present
            if "@" in clean_url:
                clean_url = "https://github.com/" + clean_url.split("github.com/", 1)[-1]
            embed.set_footer(text=f"GitHub: {clean_url}")

        await interaction.followup.send(embed=embed)
