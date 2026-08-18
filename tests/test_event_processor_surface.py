"""EventProcessor must run without importing a frontend's native objects.

These tests drive the real state machine through MemorySurface.  Discord's
adapter has its own conformance suite; this file protects the seam PR4 adds
between the session machinery and any conversation frontend.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from claude_code_core.frontend import NoticeLevel, StatusKind
from claude_code_core.memory_surface import MemorySurface
from claude_discord.claude.types import MessageType, StreamEvent, ToolCategory, ToolUseEvent
from claude_discord.cogs.event_processor import EventProcessor
from claude_discord.cogs.run_config import RunConfig


def _config(surface: MemorySurface, runner: MagicMock, **kwargs: object) -> RunConfig:
    runner.interrupt = AsyncMock()
    runner.working_dir = surface.working_dir
    runner.model = "test-model"
    runner.describe_api.return_value = None
    return RunConfig(surface=surface, runner=runner, prompt="test prompt", **kwargs)


async def test_surface_only_config_drives_session_text_and_notices() -> None:
    surface = MemorySurface()
    runner = MagicMock()
    processor = EventProcessor(_config(surface, runner))

    await processor.process(StreamEvent(message_type=MessageType.SYSTEM, session_id="session-1"))
    await processor.process(
        StreamEvent(message_type=MessageType.ASSISTANT, text="Hello from core", is_partial=False)
    )
    await processor.process(
        StreamEvent(message_type=MessageType.RESULT, is_complete=True, session_id="session-1")
    )
    await processor.finalize()

    assert surface.conformance_sent_text == ["Hello from core"]
    assert [notice.level for notice in surface.notices] == [
        NoticeLevel.INFO,
        NoticeLevel.SUCCESS,
    ]
    assert surface.statuses[-1] is StatusKind.DONE
    assert len(surface.interrupts) == 1
    assert surface.interrupts[0].disabled is True


async def test_tool_lifecycle_is_expressed_as_surface_activity() -> None:
    surface = MemorySurface()
    runner = MagicMock()
    processor = EventProcessor(_config(surface, runner))
    tool = ToolUseEvent(
        tool_id="tool-1",
        tool_name="Bash",
        tool_input={"command": "echo hi"},
        category=ToolCategory.COMMAND,
    )

    await processor.process(StreamEvent(message_type=MessageType.ASSISTANT, tool_use=tool))
    await processor.process(
        StreamEvent(
            message_type=MessageType.USER,
            tool_result_id="tool-1",
            tool_result_content="hi",
        )
    )

    assert len(surface.activities) == 1
    assert surface.activities[0].spec.title == "Running: echo hi"
    assert surface.activities[0].result == "hi"
    assert surface.activities[0].finished is True
    assert surface.statuses == [StatusKind.TOOL_COMMAND, StatusKind.THINKING]


async def test_attachment_marker_is_delivered_by_surface(tmp_path) -> None:
    output = tmp_path / "result.txt"
    output.write_text("done", encoding="utf-8")
    surface = MemorySurface(working_dir=str(tmp_path))
    marker = tmp_path / f".ccdb-attachments-{surface.thread_key}"
    marker.write_text(f"{output}\n", encoding="utf-8")
    runner = MagicMock()
    processor = EventProcessor(_config(surface, runner))

    await processor.process(StreamEvent(message_type=MessageType.RESULT, is_complete=True))

    assert surface.conformance_delivered_files == ["result.txt"]
    assert not marker.exists()


async def test_system_event_with_text_and_no_session_id_becomes_a_warning() -> None:
    """The anonymization gateway reports "sent anyway" through this path.

    Before this branch existed the session_id guard dropped the text silently,
    which is the worst possible outcome for a privacy warning.
    """
    surface = MemorySurface()
    runner = MagicMock()
    processor = EventProcessor(_config(surface, runner))

    await processor.process(
        StreamEvent(message_type=MessageType.SYSTEM, text="⚠️ possible replacement miss")
    )

    assert [notice.level for notice in surface.notices] == [NoticeLevel.WARNING]
    assert "replacement miss" in surface.notices[0].body
