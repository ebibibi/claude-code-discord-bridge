"""Permission, plan and elicitation must reach the user through the surface.

Before PR5 these three built Discord views directly, so a Teams frontend would
have had a session that streams text perfectly and then stops dead at the first
approval. These tests drive the real state machine through MemorySurface: if a
handler reaches for a native Discord object again, there is no Discord object
here to reach for.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from claude_code_core import approvals
from claude_code_core.memory_surface import MemorySurface
from claude_discord.claude.types import (
    ElicitationRequest,
    MessageType,
    PermissionRequest,
    StreamEvent,
)
from claude_discord.cogs.event_processor import EventProcessor
from claude_discord.cogs.run_config import RunConfig


def _runner(*, yolo: bool = False) -> MagicMock:
    runner = MagicMock()
    runner.interrupt = AsyncMock()
    runner.inject_tool_result = AsyncMock()
    runner.dangerously_skip_permissions = yolo
    runner.model = "test-model"
    runner.describe_api.return_value = None
    return runner


def _processor(surface: MemorySurface, runner: MagicMock, **kwargs: object) -> EventProcessor:
    runner.working_dir = surface.working_dir
    return EventProcessor(RunConfig(surface=surface, runner=runner, prompt="test prompt", **kwargs))


def _permission_event(tool: str = "Bash") -> StreamEvent:
    return StreamEvent(
        message_type=MessageType.SYSTEM,
        permission_request=PermissionRequest(
            request_id="req-1", tool_name=tool, tool_input={"command": "echo hi"}
        ),
    )


class TestPermission:
    async def test_allow_is_asked_through_the_surface_and_injected(self) -> None:
        surface = MemorySurface(answers=[[approvals.ALLOW]])
        runner = _runner()
        processor = _processor(surface, runner)

        await processor.process(_permission_event())
        await processor.wait_for_prompts()

        assert len(surface.prompts) == 1
        assert "Bash" in surface.prompts[0].question
        runner.inject_tool_result.assert_awaited_once_with("req-1", {"approved": True})

    async def test_deny_is_injected(self) -> None:
        surface = MemorySurface(answers=[[approvals.DENY]])
        runner = _runner()
        processor = _processor(surface, runner)

        await processor.process(_permission_event())
        await processor.wait_for_prompts()

        runner.inject_tool_result.assert_awaited_once_with("req-1", {"approved": False})

    async def test_unanswered_permission_fails_closed(self) -> None:
        """MemorySurface with no answers stands in for a prompt nobody replied to."""
        surface = MemorySurface()
        runner = _runner()
        processor = _processor(surface, runner)

        await processor.process(_permission_event())
        await processor.wait_for_prompts()

        runner.inject_tool_result.assert_awaited_once_with("req-1", {"approved": False})

    async def test_yolo_mode_approves_without_asking(self) -> None:
        surface = MemorySurface()
        runner = _runner(yolo=True)
        processor = _processor(surface, runner)

        await processor.process(_permission_event())
        await processor.wait_for_prompts()

        assert surface.prompts == []
        runner.inject_tool_result.assert_awaited_once_with("req-1", {"approved": True})

    async def test_asking_does_not_block_the_event_stream(self) -> None:
        """The CLI is blocked on the answer, but the reader must not be.

        A handler that awaited the user inline would stall every later event
        behind a prompt that can legitimately take two minutes.
        """
        surface = MemorySurface(answers=[[approvals.ALLOW]])
        runner = _runner()
        processor = _processor(surface, runner)

        await processor.process(_permission_event())
        await processor.process(
            StreamEvent(message_type=MessageType.ASSISTANT, text="kept going", is_partial=False)
        )
        await processor.wait_for_prompts()

        assert surface.conformance_sent_text == ["kept going"]
        runner.inject_tool_result.assert_awaited_once_with("req-1", {"approved": True})


class TestPlanApproval:
    def _event(self) -> StreamEvent:
        return StreamEvent(
            message_type=MessageType.ASSISTANT, is_plan_approval=True, text="1. do the thing"
        )

    async def test_approval_is_asked_and_injected_against_the_session_id(self) -> None:
        surface = MemorySurface(answers=[[approvals.APPROVE]])
        runner = _runner()
        processor = _processor(surface, runner, session_id="session-9")

        await processor.process(self._event())
        await processor.wait_for_prompts()

        assert "do the thing" in surface.prompts[0].question
        runner.inject_tool_result.assert_awaited_once_with("session-9", {"approved": True})

    async def test_unanswered_plan_cancels(self) -> None:
        surface = MemorySurface()
        runner = _runner()
        processor = _processor(surface, runner, session_id="session-9")

        await processor.process(self._event())
        await processor.wait_for_prompts()

        runner.inject_tool_result.assert_awaited_once_with("session-9", {"approved": False})


class TestElicitation:
    async def test_url_mode_delivers_the_link_then_confirms(self) -> None:
        surface = MemorySurface(answers=[[approvals.DONE]])
        runner = _runner()
        processor = _processor(surface, runner)

        await processor.process(
            StreamEvent(
                message_type=MessageType.SYSTEM,
                elicitation=ElicitationRequest(
                    request_id="e-1",
                    server_name="github",
                    mode="url-mode",
                    message="Authorize",
                    url="https://example.test/auth",
                ),
            )
        )
        await processor.wait_for_prompts()

        assert surface.urls == [("Open link", "https://example.test/auth")]
        runner.inject_tool_result.assert_awaited_once_with("e-1", {"completed": True})

    async def test_form_mode_injects_submitted_values(self) -> None:
        surface = MemorySurface(form_answers=[{"summary": "hello"}])
        runner = _runner()
        processor = _processor(surface, runner)

        await processor.process(
            StreamEvent(
                message_type=MessageType.SYSTEM,
                elicitation=ElicitationRequest(
                    request_id="e-2",
                    server_name="jira",
                    mode="form-mode",
                    schema={"properties": {"summary": {"type": "string"}}},
                ),
            )
        )
        await processor.wait_for_prompts()

        assert [f.key for f in surface.forms[0].fields] == ["summary"]
        runner.inject_tool_result.assert_awaited_once_with("e-2", {"values": {"summary": "hello"}})

    async def test_abandoned_form_reports_incomplete_rather_than_empty(self) -> None:
        surface = MemorySurface()
        runner = _runner()
        processor = _processor(surface, runner)

        await processor.process(
            StreamEvent(
                message_type=MessageType.SYSTEM,
                elicitation=ElicitationRequest(
                    request_id="e-3", server_name="jira", mode="form-mode", schema={}
                ),
            )
        )
        await processor.wait_for_prompts()

        runner.inject_tool_result.assert_awaited_once_with("e-3", {"completed": False})


async def test_a_failing_prompt_does_not_leave_the_cli_waiting() -> None:
    """If the surface itself breaks, the session must still be told something."""
    surface = MemorySurface()
    surface.prompt_choice = AsyncMock(side_effect=RuntimeError("surface down"))  # type: ignore[method-assign]
    runner = _runner()
    processor = _processor(surface, runner)

    await processor.process(_permission_event())
    await processor.wait_for_prompts()

    runner.inject_tool_result.assert_awaited_once_with("req-1", {"approved": False})
