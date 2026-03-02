"""Build a prompt string and collect image URLs from a Discord message.

Extracted from ClaudeChatCog to keep the Cog thin.  This module is a
pure function layer — it only depends on ``discord.Message`` and has no
Cog or Bot state.
"""

from __future__ import annotations

import logging
import os.path

import discord

logger = logging.getLogger(__name__)

# Attachment filtering constants
ALLOWED_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
)
IMAGE_MIME_PREFIXES = ("image/",)

# File extensions treated as text when content_type is absent.
# Discord converts long pasted text to "message.txt" without a content_type.
_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt",
        ".md",
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".csv",
        ".log",
        ".sh",
        ".bash",
        ".zsh",
        ".html",
        ".css",
        ".xml",
        ".rst",
        ".sql",
        ".graphql",
        ".tf",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".cs",
        ".rb",
        ".php",
    }
)

# Image file extensions used as fallback when content_type is absent.
_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
    }
)
MAX_ATTACHMENT_BYTES = (
    200_000  # 200 KB per file — Discord auto-converted messages can exceed 100 KB
)
MAX_IMAGE_BYTES = 5_000_000  # 5 MB per image
MAX_TOTAL_BYTES = 500_000  # 500 KB across all text attachments
MAX_ATTACHMENTS = 5
MAX_IMAGES = 4  # Claude supports up to 4 images per prompt


# Keywords that indicate the user wants a file sent/attached.
_SEND_FILE_KEYWORDS = (
    "送って",
    "ちょうだい",
    "添付して",
    "くれ",
    "送ってください",
    "ください",
    "attach",
    "send me",
    "send the file",
    "give me",
    "download",
)


def wants_file_attachment(prompt: str) -> bool:
    """Return True if *prompt* contains a file-send/attach request.

    Used to enable the ``.ccdb-attachments`` delivery mechanism for the
    session — Claude is instructed to write the paths it wants to send,
    and the bot attaches them when the session completes.
    """
    lower = prompt.lower()
    return any(kw in lower for kw in _SEND_FILE_KEYWORDS)


async def build_prompt_and_images(message: discord.Message) -> tuple[str, list[str]]:
    """Build the prompt string and collect image attachment URLs.

    Text attachments (text/*, application/json, application/xml) are appended
    inline to the prompt.  Image attachments (image/*) are collected as HTTPS
    URLs (Discord CDN) and returned for stream-json input to Claude Code CLI.

    Claude Code CLI silently drops base64 image blocks in stream-json mode.
    Passing Discord CDN URLs directly as ``{"type": "url"}`` image sources is
    the only format the CLI forwards to the Anthropic API.

    Both binary-file types that exceed size limits and unsupported types are
    silently skipped — never raise an error to the user.

    Returns:
        (prompt_text, image_urls) — HTTPS URLs for stream-json url-type blocks.
    """
    prompt = message.content or ""
    if not message.attachments:
        return prompt, []

    total_bytes = 0
    sections: list[str] = []
    image_urls: list[str] = []

    for attachment in message.attachments[:MAX_ATTACHMENTS]:
        content_type = attachment.content_type or ""

        # When Discord auto-converts a long pasted message to a file, the
        # content_type may be absent.  Fall back to extension-based detection.
        if not content_type:
            ext = os.path.splitext(attachment.filename.lower())[1]
            if ext in _IMAGE_EXTENSIONS:
                content_type = "image/png"  # triggers CDN URL path below
            elif ext in _TEXT_EXTENSIONS:
                content_type = "text/plain"

        # ---- Image attachments → collect CDN URL for stream-json input ----
        if content_type.startswith(IMAGE_MIME_PREFIXES):
            if len(image_urls) >= MAX_IMAGES:
                logger.debug("Skipping image %s: max images reached", attachment.filename)
                continue
            if attachment.size > MAX_IMAGE_BYTES:
                logger.debug(
                    "Skipping image %s: too large (%d bytes)",
                    attachment.filename,
                    attachment.size,
                )
                continue
            image_urls.append(attachment.url)
            logger.debug("Collected image URL for %s: %.80s", attachment.filename, attachment.url)
            continue

        # ---- Text attachments → inline in prompt ----
        if not content_type.startswith(ALLOWED_MIME_PREFIXES):
            logger.debug(
                "Skipping attachment %s: unsupported type %s",
                attachment.filename,
                content_type,
            )
            continue
        total_bytes += min(attachment.size, MAX_ATTACHMENT_BYTES)
        if total_bytes > MAX_TOTAL_BYTES:
            logger.debug("Stopping attachment processing: total size exceeded")
            break
        try:
            data = await attachment.read()
            text = data.decode("utf-8", errors="replace")
            if len(text) > MAX_ATTACHMENT_BYTES:
                truncated_chars = MAX_ATTACHMENT_BYTES
                notice = (
                    f"\n... [truncated: showing first {truncated_chars // 1000}KB"
                    f" of {len(text) // 1000}KB]"
                )
                text = text[:truncated_chars] + notice
                logger.debug(
                    "Truncated attachment %s from %d to %d chars",
                    attachment.filename,
                    len(data),
                    truncated_chars,
                )
            sections.append(f"\n\n--- Attached file: {attachment.filename} ---\n{text}")
        except Exception:
            logger.debug("Failed to read attachment %s", attachment.filename, exc_info=True)
            continue

    return prompt + "".join(sections), image_urls
