"""Parser for Claude Code CLI stream-json output.

Each line of stdout is a JSON object. This module parses them into StreamEvent objects.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .types import (
    TOOL_CATEGORIES,
    ContentBlockType,
    MessageType,
    StreamEvent,
    ToolCategory,
    ToolUseEvent,
)

logger = logging.getLogger(__name__)


def parse_line(line: str) -> StreamEvent | None:
    """Parse a single line of stream-json output into a StreamEvent.

    Returns None if the line is empty or unparseable.
    """
    line = line.strip()
    if not line:
        return None

    try:
        data: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("Failed to parse stream-json line: %s", line[:200])
        return None

    msg_type_str = data.get("type", "")
    try:
        msg_type = MessageType(msg_type_str)
    except ValueError:
        logger.debug("Unknown message type: %s", msg_type_str)
        return None

    event = StreamEvent(message_type=msg_type)

    if msg_type == MessageType.SYSTEM:
        _parse_system(data, event)
    elif msg_type == MessageType.ASSISTANT:
        _parse_assistant(data, event)
    elif msg_type == MessageType.USER:
        _parse_user(data, event)
    elif msg_type == MessageType.RESULT:
        _parse_result(data, event)

    return event


def _parse_system(data: dict[str, Any], event: StreamEvent) -> None:
    """Parse system message (contains session_id on init)."""
    event.session_id = data.get("session_id")
    subtype = data.get("subtype", "")
    if subtype == "init":
        logger.info("Session initialized: %s", event.session_id)


def _parse_assistant(data: dict[str, Any], event: StreamEvent) -> None:
    """Parse assistant message (text blocks and tool_use blocks)."""
    message = data.get("message", {})
    content = message.get("content", [])

    text_parts: list[str] = []
    for block in content:
        block_type = block.get("type", "")

        if block_type == ContentBlockType.TEXT.value:
            text = block.get("text", "")
            if text:
                text_parts.append(text)

        elif block_type == ContentBlockType.TOOL_USE.value:
            tool_name = block.get("name", "unknown")
            category = TOOL_CATEGORIES.get(tool_name, ToolCategory.OTHER)
            event.tool_use = ToolUseEvent(
                tool_id=block.get("id", ""),
                tool_name=tool_name,
                tool_input=block.get("input", {}),
                category=category,
            )

    if text_parts:
        event.text = "\n".join(text_parts)


def _parse_user(data: dict[str, Any], event: StreamEvent) -> None:
    """Parse user message (tool_result blocks)."""
    message = data.get("message", {})
    content = message.get("content", [])

    for block in content:
        if block.get("type") == ContentBlockType.TOOL_RESULT.value:
            event.tool_result_id = block.get("tool_use_id", "")
            break


def _parse_result(data: dict[str, Any], event: StreamEvent) -> None:
    """Parse result message (session complete)."""
    event.is_complete = True
    event.session_id = data.get("session_id")
    event.cost_usd = data.get("cost_usd")
    event.duration_ms = data.get("duration_ms")

    # Final text from result
    result_text = data.get("result", "")
    if result_text:
        event.text = result_text

    # Check for errors
    subtype = data.get("subtype", "")
    if subtype == "error":
        event.error = data.get("error", "Unknown error")
