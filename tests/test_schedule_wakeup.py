"""Tests for ScheduleWakeup tool support.

Claude models with the /loop dynamic-pacing harness (e.g. Fable) may call a
``ScheduleWakeup`` tool expecting the harness to re-invoke them after a delay.
In ``claude -p`` (ccdb) there is no such harness, so without handling the
session would simply end and the loop dies.

ccdb bridges this by detecting the tool call and registering a one-shot
scheduled task (existing SQLite scheduler) that resumes the session in the
same thread after the requested delay.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from claude_discord.claude.types import (
    MessageType,
    StreamEvent,
    ToolCategory,
    ToolUseEvent,
)
from claude_discord.cogs import _run_helper
from claude_discord.cogs._run_helper import (
    configure_wakeup_scheduler,
    run_claude_with_config,
)
from claude_discord.cogs.event_processor import EventProcessor
from claude_discord.cogs.run_config import RunConfig
from claude_discord.database.task_repo import TaskRepository

from .conftest import make_async_gen


def _wakeup_event(
    delay: int = 235,
    prompt: str = "/loop check the deploy",
    reason: str = "watching CI run",
) -> StreamEvent:
    return StreamEvent(
        message_type=MessageType.ASSISTANT,
        tool_use=ToolUseEvent(
            tool_id="wakeup-1",
            tool_name="ScheduleWakeup",
            tool_input={"delaySeconds": delay, "prompt": prompt, "reason": reason},
            category=ToolCategory.OTHER,
        ),
    )


def _result_event(session_id: str = "sess-1") -> StreamEvent:
    return StreamEvent(
        message_type=MessageType.RESULT,
        is_complete=True,
        session_id=session_id,
    )


@pytest.fixture(autouse=True)
def _reset_wakeup_repo():
    """Keep the module-level wakeup repo isolated between tests."""
    original = _run_helper._wakeup_task_repo
    _run_helper._wakeup_task_repo = None
    yield
    _run_helper._wakeup_task_repo = original


class TestEventProcessorWakeupCapture:
    """EventProcessor should capture ScheduleWakeup tool calls."""

    def test_pending_wakeup_none_initially(self, thread: MagicMock, runner: MagicMock) -> None:
        p = EventProcessor(RunConfig(thread=thread, runner=runner, prompt="x"))
        assert p.pending_wakeup is None

    @pytest.mark.asyncio
    async def test_captures_schedule_wakeup_input(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        p = EventProcessor(RunConfig(thread=thread, runner=runner, prompt="x"))
        await p.process(_wakeup_event(delay=300, prompt="/loop poll", reason="poll CI"))
        assert p.pending_wakeup == {
            "delaySeconds": 300,
            "prompt": "/loop poll",
            "reason": "poll CI",
        }

    @pytest.mark.asyncio
    async def test_last_wakeup_wins(self, thread: MagicMock, runner: MagicMock) -> None:
        p = EventProcessor(RunConfig(thread=thread, runner=runner, prompt="x"))
        await p.process(_wakeup_event(delay=100))
        await p.process(_wakeup_event(delay=900))
        assert p.pending_wakeup is not None
        assert p.pending_wakeup["delaySeconds"] == 900

    @pytest.mark.asyncio
    async def test_captured_in_chat_only_mode(self, thread: MagicMock, runner: MagicMock) -> None:
        p = EventProcessor(RunConfig(thread=thread, runner=runner, prompt="x", chat_only=True))
        await p.process(_wakeup_event())
        assert p.pending_wakeup is not None

    @pytest.mark.asyncio
    async def test_other_tools_do_not_set_wakeup(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        p = EventProcessor(RunConfig(thread=thread, runner=runner, prompt="x"))
        await p.process(
            StreamEvent(
                message_type=MessageType.ASSISTANT,
                tool_use=ToolUseEvent(
                    tool_id="t1",
                    tool_name="Bash",
                    tool_input={"command": "echo hi"},
                    category=ToolCategory.COMMAND,
                ),
            )
        )
        assert p.pending_wakeup is None


class TestScheduleWakeupTaskRegistration:
    """run_claude_with_config should register a one-shot task on wakeup."""

    @pytest.mark.asyncio
    async def test_registers_one_shot_task(self, thread: MagicMock, runner: MagicMock) -> None:
        task_repo = MagicMock()
        task_repo.delete_by_name = AsyncMock(return_value=False)
        task_repo.create = AsyncMock(return_value=1)
        configure_wakeup_scheduler(task_repo)

        runner.run = make_async_gen([_wakeup_event(delay=235), _result_event()])
        runner.working_dir = "/tmp/wd"
        thread.parent_id = 999

        await run_claude_with_config(RunConfig(thread=thread, runner=runner, prompt="go"))

        task_repo.create.assert_awaited_once()
        kwargs = task_repo.create.await_args.kwargs
        assert kwargs["name"] == f"wakeup-thread-{thread.id}"
        assert kwargs["prompt"] == "/loop check the deploy"
        assert kwargs["interval_seconds"] == 235
        assert kwargs["channel_id"] == 999
        assert kwargs["thread_id"] == thread.id
        assert kwargs["one_shot"] is True
        assert kwargs["run_immediately"] is False
        assert kwargs["working_dir"] == "/tmp/wd"

    @pytest.mark.asyncio
    async def test_replaces_existing_wakeup_task(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        task_repo = MagicMock()
        task_repo.delete_by_name = AsyncMock(return_value=True)
        task_repo.create = AsyncMock(return_value=2)
        configure_wakeup_scheduler(task_repo)

        runner.run = make_async_gen([_wakeup_event(), _result_event()])
        runner.working_dir = None
        thread.parent_id = 999

        await run_claude_with_config(RunConfig(thread=thread, runner=runner, prompt="go"))

        task_repo.delete_by_name.assert_awaited_once_with(f"wakeup-thread-{thread.id}")

    @pytest.mark.asyncio
    async def test_delay_clamped_to_range(self, thread: MagicMock, runner: MagicMock) -> None:
        task_repo = MagicMock()
        task_repo.delete_by_name = AsyncMock(return_value=False)
        task_repo.create = AsyncMock(return_value=1)
        configure_wakeup_scheduler(task_repo)

        runner.run = make_async_gen([_wakeup_event(delay=5), _result_event()])
        runner.working_dir = None
        thread.parent_id = 999

        await run_claude_with_config(RunConfig(thread=thread, runner=runner, prompt="go"))

        assert task_repo.create.await_args.kwargs["interval_seconds"] == 60

    @pytest.mark.asyncio
    async def test_autonomous_loop_sentinel_rewritten(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        task_repo = MagicMock()
        task_repo.delete_by_name = AsyncMock(return_value=False)
        task_repo.create = AsyncMock(return_value=1)
        configure_wakeup_scheduler(task_repo)

        runner.run = make_async_gen(
            [_wakeup_event(prompt="<<autonomous-loop-dynamic>>"), _result_event()]
        )
        runner.working_dir = None
        thread.parent_id = 999

        await run_claude_with_config(RunConfig(thread=thread, runner=runner, prompt="go"))

        prompt = task_repo.create.await_args.kwargs["prompt"]
        assert "<<autonomous-loop-dynamic>>" not in prompt
        assert prompt  # non-empty fallback instruction

    @pytest.mark.asyncio
    async def test_no_task_repo_configured_is_noop(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        """Without a configured repo, the run completes without errors."""
        runner.run = make_async_gen([_wakeup_event(), _result_event()])
        runner.working_dir = None

        session_id = await run_claude_with_config(
            RunConfig(thread=thread, runner=runner, prompt="go")
        )
        assert session_id == "sess-1"

    @pytest.mark.asyncio
    async def test_no_wakeup_means_no_task(self, thread: MagicMock, runner: MagicMock) -> None:
        task_repo = MagicMock()
        task_repo.delete_by_name = AsyncMock(return_value=False)
        task_repo.create = AsyncMock(return_value=1)
        configure_wakeup_scheduler(task_repo)

        runner.run = make_async_gen([_result_event()])
        runner.working_dir = None

        await run_claude_with_config(RunConfig(thread=thread, runner=runner, prompt="go"))

        task_repo.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_repo_failure_does_not_break_session(
        self, thread: MagicMock, runner: MagicMock
    ) -> None:
        task_repo = MagicMock()
        task_repo.delete_by_name = AsyncMock(side_effect=RuntimeError("db locked"))
        task_repo.create = AsyncMock(return_value=1)
        configure_wakeup_scheduler(task_repo)

        runner.run = make_async_gen([_wakeup_event(), _result_event()])
        runner.working_dir = None
        thread.parent_id = 999

        session_id = await run_claude_with_config(
            RunConfig(thread=thread, runner=runner, prompt="go")
        )
        assert session_id == "sess-1"


class TestTaskRepositoryDeleteByName:
    """TaskRepository.delete_by_name removes a task row by its unique name."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, tmp_path) -> None:
        repo = TaskRepository(str(tmp_path / "tasks.db"))
        await repo.init_db()
        task_id = await repo.create(
            name="wakeup-thread-1", prompt="p", interval_seconds=60, channel_id=1
        )
        assert await repo.delete_by_name("wakeup-thread-1") is True
        assert await repo.get(task_id) is None

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, tmp_path) -> None:
        repo = TaskRepository(str(tmp_path / "tasks.db"))
        await repo.init_db()
        assert await repo.delete_by_name("nope") is False
