"""Build a prompt string and collect image data from a Discord message.

Extracted from ClaudeChatCog to keep the Cog thin.  This module is a
pure function layer — it only depends on ``discord.Message`` and has no
Cog or Bot state.
"""

from __future__ import annotations

import base64
import logging
import os.path

import discord

from ..claude.types import ImageData

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

# Media types accepted by the Anthropic API for base64 image blocks.
_SUPPORTED_MEDIA_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)

# Extension → media type mapping for fallback detection.
_EXT_TO_MEDIA_TYPE: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/jpeg",  # BMP will be treated as JPEG after download
    ".svg": "image/png",  # SVG not supported by API
}


def _detect_media_type(content_type: str, filename: str) -> str:
    """Determine the media type from content_type header or filename extension."""
    # Try content_type first (e.g. "image/png; charset=utf-8" → "image/png")
    if content_type:
        mt = content_type.split(";")[0].strip().lower()
        if mt in _SUPPORTED_MEDIA_TYPES:
            return mt
    # Fallback to extension
    ext = os.path.splitext(filename.lower())[1]
    return _EXT_TO_MEDIA_TYPE.get(ext, "image/jpeg")


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


async def build_prompt_and_images(
    message: discord.Message,
) -> tuple[str, list[ImageData]]:
    """Build the prompt string and collect image attachments as base64 data.

    Text attachments (text/*, application/json, application/xml) are appended
    inline to the prompt.  Image attachments (image/*) are downloaded from the
    Discord CDN and returned as base64-encoded ``ImageData`` objects for
    stream-json input to Claude Code CLI.

    Images are downloaded and base64-encoded on the ccdb side rather than
    passing Discord CDN URLs directly.  This avoids issues where the CLI's
    internal URL-fetch-to-base64 conversion rejects certain image formats
    (e.g. PNG — see GitHub issue for details).

    Both binary-file types that exceed size limits and unsupported types are
    silently skipped — never raise an error to the user.

    Returns:
        (prompt_text, images) — base64-encoded image data for stream-json blocks.
    """
    prompt = message.content or ""
    if not message.attachments:
        return prompt, []

    total_bytes = 0
    sections: list[str] = []
    images: list[ImageData] = []

    for attachment in message.attachments[:MAX_ATTACHMENTS]:
        content_type = attachment.content_type or ""

        # When Discord auto-converts a long pasted message to a file, the
        # content_type may be absent.  Fall back to extension-based detection.
        if not content_type:
            ext = os.path.splitext(attachment.filename.lower())[1]
            if ext in _IMAGE_EXTENSIONS:
                content_type = "image/png"  # triggers image download path below
            elif ext in _TEXT_EXTENSIONS:
                content_type = "text/plain"

        # ---- Image attachments → download and base64-encode ----
        if content_type.startswith(IMAGE_MIME_PREFIXES):
            if len(images) >= MAX_IMAGES:
                logger.debug("Skipping image %s: max images reached", attachment.filename)
                continue
            if attachment.size > MAX_IMAGE_BYTES:
                logger.debug(
                    "Skipping image %s: too large (%d bytes)",
                    attachment.filename,
                    attachment.size,
                )
                continue
            try:
                raw = await attachment.read()
                media_type = _detect_media_type(content_type, attachment.filename)
                encoded = base64.standard_b64encode(raw).decode("ascii")
                images.append(ImageData(data=encoded, media_type=media_type))
                logger.debug(
                    "Downloaded and encoded image %s (%d bytes, %s)",
                    attachment.filename,
                    len(raw),
                    media_type,
                )
            except Exception:
                logger.debug("Failed to download image %s", attachment.filename, exc_info=True)
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

    return prompt + "".join(sections), images
