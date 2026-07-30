"""Tests for frontend-neutral stream presentation policy."""

from __future__ import annotations

from claude_code_core.presentation import (
    ErrorProjection,
    FinalResult,
    InteractiveProjection,
    PresentationMode,
    PresentationPolicy,
    StreamProjector,
    TextUpdate,
    project_stream,
)
from claude_code_core.types import (
    AskQuestion,
    ElicitationRequest,
    MessageType,
    PermissionRequest,
    StreamEvent,
    ToolCategory,
    ToolUseEvent,
)


def _assistant(text: str, *, tool: bool = False) -> StreamEvent:
    return StreamEvent(
        message_type=MessageType.ASSISTANT,
        text=text,
        tool_use=(
            ToolUseEvent("tool-1", "Read", {"file_path": "README.md"}, ToolCategory.READ)
            if tool
            else None
        ),
    )


def test_stream_mode_is_the_backward_compatible_default() -> None:
    projector = StreamProjector()

    assert projector.mode is PresentationMode.STREAM
    assert projector.project(_assistant("working")) == (TextUpdate("working"),)


def test_projector_accepts_an_explicit_policy() -> None:
    projector = StreamProjector(PresentationPolicy(mode=PresentationMode.FINAL))

    assert projector.mode is PresentationMode.FINAL


def test_final_mode_emits_only_one_terminal_result_across_commentary_and_tools() -> None:
    projector = StreamProjector(PresentationMode.FINAL)

    emitted = []
    emitted.extend(projector.project(_assistant("I will inspect the files.")))
    emitted.extend(projector.project(_assistant("Reading now.", tool=True)))
    emitted.extend(projector.project(_assistant("The tests reveal the cause.")))
    emitted.extend(
        projector.project(
            StreamEvent(
                message_type=MessageType.RESULT,
                text="Fixed and verified.",
                is_complete=True,
            )
        )
    )

    assert emitted == [FinalResult("Fixed and verified.")]


def test_final_mode_never_emits_empty_text() -> None:
    projector = StreamProjector(PresentationMode.FINAL)

    assert projector.project(_assistant("")) == ()
    assert projector.project(StreamEvent(message_type=MessageType.RESULT, is_complete=True)) == ()


def test_final_mode_emits_interactive_requests_immediately() -> None:
    events = [
        StreamEvent(
            message_type=MessageType.ASSISTANT,
            ask_questions=[AskQuestion("Continue?")],
        ),
        StreamEvent(
            message_type=MessageType.SYSTEM,
            permission_request=PermissionRequest("p1", "Bash"),
        ),
        StreamEvent(
            message_type=MessageType.SYSTEM,
            elicitation=ElicitationRequest("e1", "server", "form-mode"),
        ),
        StreamEvent(message_type=MessageType.ASSISTANT, is_plan_approval=True),
    ]

    for event in events:
        projector = StreamProjector(PresentationMode.FINAL)
        assert projector.project(event) == (InteractiveProjection(event),)


def test_final_mode_emits_errors_immediately_without_a_final_result() -> None:
    projector = StreamProjector(PresentationMode.FINAL)
    projector.project(_assistant("Trying a fallback."))
    event = StreamEvent(
        message_type=MessageType.RESULT,
        error="backend unavailable",
        is_complete=True,
    )

    assert projector.project(event) == (ErrorProjection("backend unavailable", event),)
    assert (
        projector.project(
            StreamEvent(message_type=MessageType.RESULT, text="must not leak", is_complete=True)
        )
        == ()
    )


async def test_project_stream_projects_an_async_backend_stream() -> None:
    async def events():
        yield _assistant("Working")
        yield StreamEvent(message_type=MessageType.RESULT, text="Done", is_complete=True)

    projections = [
        projection
        async for projection in project_stream(
            events(), PresentationPolicy(mode=PresentationMode.FINAL)
        )
    ]

    assert projections == [FinalResult("Done")]
