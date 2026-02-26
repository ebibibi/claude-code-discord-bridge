"""Tests for stream-json parser."""

import json

from claude_discord.claude.parser import parse_line
from claude_discord.claude.types import MessageType, ToolCategory


class TestParseLine:
    def test_empty_line_returns_none(self):
        assert parse_line("") is None
        assert parse_line("  ") is None

    def test_invalid_json_returns_none(self):
        assert parse_line("not json") is None

    def test_unknown_type_returns_none(self):
        assert parse_line('{"type": "unknown_type"}') is None

    def test_system_init(self):
        line = '{"type": "system", "subtype": "init", "session_id": "abc-123"}'
        event = parse_line(line)
        assert event is not None
        assert event.message_type == MessageType.SYSTEM
        assert event.session_id == "abc-123"

    def test_assistant_text(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "text", "text": "Hello world"}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.message_type == MessageType.ASSISTANT
        assert event.text == "Hello world"

    def test_assistant_tool_use(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "tool_use", "id": "tool-1", "name": "Read", '
            '"input": {"file_path": "/tmp/test.py"}}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.tool_use is not None
        assert event.tool_use.tool_name == "Read"
        assert event.tool_use.category == ToolCategory.READ
        assert "Reading: /tmp/test.py" in event.tool_use.display_name

    def test_assistant_bash_tool(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "tool_use", "id": "tool-2", "name": "Bash", '
            '"input": {"command": "ls -la"}}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.tool_use is not None
        assert event.tool_use.category == ToolCategory.COMMAND
        assert "Running: ls -la" in event.tool_use.display_name

    def test_user_tool_result(self):
        line = (
            '{"type": "user", "message": {"content": '
            '[{"type": "tool_result", "tool_use_id": "tool-1"}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.message_type == MessageType.USER
        assert event.tool_result_id == "tool-1"

    def test_result_success(self):
        line = (
            '{"type": "result", "session_id": "abc-123", '
            '"result": "Done!", "cost_usd": 0.0042, "duration_ms": 1500}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.is_complete is True
        assert event.session_id == "abc-123"
        assert event.text == "Done!"
        assert event.cost_usd == 0.0042
        assert event.duration_ms == 1500

    def test_result_error(self):
        line = '{"type": "result", "subtype": "error", "error": "Something broke"}'
        event = parse_line(line)
        assert event is not None
        assert event.is_complete is True
        assert event.error == "Something broke"

    def test_result_is_error_true_promoted_to_event_error(self):
        """API-level errors come as subtype=success + is_error=true + result=<error text>.

        Previously parse_line only checked subtype=="error", so these were silently
        swallowed — the Discord handler showed a successful session_complete embed
        instead of an error embed.  Now is_error:true must promote event.error.
        """
        line = (
            '{"type": "result", "subtype": "success", "is_error": true, '
            '"result": "API Error: 400 {\\"type\\":\\"error\\",\\"error\\":{'
            '\\"type\\":\\"invalid_request_error\\",\\"message\\":\\"messages: '
            'text content blocks must be non-empty\\"}}", '
            '"session_id": "abc-123", "duration_ms": 965}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.is_complete is True
        assert event.error is not None
        assert "400" in event.error
        assert "non-empty" in event.error
        # result text must be cleared to avoid duplicate display
        assert event.text == ""


class TestToolResultContent:
    def test_tool_result_string_content(self):
        line = (
            '{"type": "user", "message": {"content": '
            '[{"type": "tool_result", "tool_use_id": "tool-1", '
            '"content": "file contents here"}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.tool_result_id == "tool-1"
        assert event.tool_result_content == "file contents here"

    def test_tool_result_list_content(self):
        line = (
            '{"type": "user", "message": {"content": '
            '[{"type": "tool_result", "tool_use_id": "tool-1", '
            '"content": [{"type": "text", "text": "line 1"}, '
            '{"type": "text", "text": "line 2"}]}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.tool_result_content == "line 1\nline 2"

    def test_tool_result_empty_content(self):
        line = (
            '{"type": "user", "message": {"content": '
            '[{"type": "tool_result", "tool_use_id": "tool-1", '
            '"content": ""}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.tool_result_content is None

    def test_tool_result_no_content_field(self):
        line = (
            '{"type": "user", "message": {"content": '
            '[{"type": "tool_result", "tool_use_id": "tool-1"}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.tool_result_content is None


class TestThinkingContent:
    def test_assistant_thinking_block(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "thinking", "thinking": "Let me analyze this problem..."}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.thinking == "Let me analyze this problem..."

    def test_assistant_thinking_and_text(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "thinking", "thinking": "Hmm..."}, '
            '{"type": "text", "text": "Here is my answer."}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.thinking == "Hmm..."
        assert event.text == "Here is my answer."

    def test_empty_thinking_ignored(self):
        line = (
            '{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": ""}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.thinking is None


class TestToolDisplayNames:
    def test_read_display(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "tool_use", "id": "t1", "name": "Read", '
            '"input": {"file_path": "/home/user/code.py"}}]}}'
        )
        event = parse_line(line)
        assert event.tool_use.display_name == "Reading: /home/user/code.py"

    def test_edit_display(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "tool_use", "id": "t1", "name": "Edit", '
            '"input": {"file_path": "/tmp/x.py", "old_string": "a", "new_string": "b"}}]}}'
        )
        event = parse_line(line)
        assert event.tool_use.display_name == "Editing: /tmp/x.py"

    def test_grep_display(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "tool_use", "id": "t1", "name": "Grep", '
            '"input": {"pattern": "TODO"}}]}}'
        )
        event = parse_line(line)
        assert event.tool_use.display_name == "Searching: TODO"

    def test_long_bash_command_truncated(self):
        long_cmd = "a" * 100
        line = (
            '{"type": "assistant", "message": {"content": '
            f'[{{"type": "tool_use", "id": "t1", "name": "Bash", '
            f'"input": {{"command": "{long_cmd}"}}}}]}}}}'
        )
        event = parse_line(line)
        assert len(event.tool_use.display_name) < 80
        assert event.tool_use.display_name.endswith("...")

    def test_websearch_display(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "tool_use", "id": "t1", "name": "WebSearch", '
            '"input": {"query": "python asyncio tutorial"}}]}}'
        )
        event = parse_line(line)
        assert event.tool_use.display_name == "Searching web: python asyncio tutorial"


class TestTokenUsage:
    def test_result_with_usage(self):
        line = (
            '{"type": "result", "subtype": "success", "session_id": "s1",'
            ' "cost_usd": 0.01, "duration_ms": 1000,'
            ' "usage": {"input_tokens": 500, "output_tokens": 200,'
            ' "cache_read_input_tokens": 300}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.input_tokens == 500
        assert event.output_tokens == 200
        assert event.cache_read_tokens == 300

    def test_result_without_usage(self):
        line = '{"type": "result", "subtype": "success", "session_id": "s1"}'
        event = parse_line(line)
        assert event is not None
        assert event.input_tokens is None
        assert event.output_tokens is None
        assert event.cache_read_tokens is None

    def test_result_with_empty_usage(self):
        line = '{"type": "result", "subtype": "success", "session_id": "s1", "usage": {}}'
        event = parse_line(line)
        assert event is not None
        assert event.input_tokens is None


class TestRedactedThinking:
    def test_redacted_thinking_sets_flag(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "redacted_thinking", "data": "opaque-blob"}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.has_redacted_thinking is True

    def test_normal_thinking_does_not_set_flag(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "thinking", "thinking": "Let me reason..."}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.has_redacted_thinking is False

    def test_redacted_thinking_alongside_text(self):
        line = (
            '{"type": "assistant", "message": {"content": '
            '[{"type": "redacted_thinking", "data": "blob"}, '
            '{"type": "text", "text": "Here is my answer."}]}}'
        )
        event = parse_line(line)
        assert event is not None
        assert event.has_redacted_thinking is True
        assert event.text == "Here is my answer."


class TestCompactBoundary:
    """Tests for compact_boundary system event parsing."""

    def test_compact_boundary_auto(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "compact_boundary",
                "content": "Conversation compacted",
                "compactMetadata": {"trigger": "auto", "preTokens": 167745},
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.message_type == MessageType.SYSTEM
        assert event.is_compact is True
        assert event.compact_trigger == "auto"
        assert event.compact_pre_tokens == 167745

    def test_compact_boundary_manual(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "compact_boundary",
                "compactMetadata": {"trigger": "manual"},
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.is_compact is True
        assert event.compact_trigger == "manual"
        assert event.compact_pre_tokens is None

    def test_compact_boundary_no_metadata(self) -> None:
        line = json.dumps(
            {
                "type": "system",
                "subtype": "compact_boundary",
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.is_compact is True
        assert event.compact_trigger is None


class TestContextWindow:
    """Tests for context_window extraction from RESULT events."""

    def test_context_window_from_model_usage(self) -> None:
        line = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "done",
                "session_id": "abc",
                "usage": {"input_tokens": 50000, "output_tokens": 1000},
                "modelUsage": {
                    "claude-opus-4-6": {
                        "inputTokens": 50000,
                        "outputTokens": 1000,
                        "contextWindow": 200000,
                    }
                },
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.context_window == 200000

    def test_context_window_missing(self) -> None:
        line = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "done",
                "usage": {"input_tokens": 100, "output_tokens": 50},
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.context_window is None

    def test_context_window_multiple_models(self) -> None:
        """First model with contextWindow wins."""
        line = json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "done",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "modelUsage": {
                    "claude-sonnet-4-6": {"contextWindow": 200000},
                    "claude-haiku-4-5": {"contextWindow": 200000},
                },
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.context_window == 200000


class TestProgressEvent:
    """Tests for progress event type."""

    def test_progress_event_parsed(self) -> None:
        line = json.dumps(
            {
                "type": "progress",
                "data": {"message": {"type": "assistant"}},
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.message_type == MessageType.PROGRESS

    def test_progress_event_minimal(self) -> None:
        line = json.dumps({"type": "progress"})
        event = parse_line(line)
        assert event is not None
        assert event.message_type == MessageType.PROGRESS


class TestTodoWriteParsing:
    """Tests for TodoWrite tool input parsing."""

    def _make_todo_line(self, todos: list[dict]) -> str:
        import json

        return json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "todo-1",
                            "name": "TodoWrite",
                            "input": {"todos": todos},
                        }
                    ]
                },
            }
        )

    def test_todo_write_parsed(self):
        todos = [
            {"content": "Write tests", "status": "completed", "activeForm": "Writing tests"},
            {
                "content": "Implement feature",
                "status": "in_progress",
                "activeForm": "Implementing feature",
            },
            {"content": "Submit PR", "status": "pending", "activeForm": "Submitting PR"},
        ]
        event = parse_line(self._make_todo_line(todos))
        assert event is not None
        assert event.todo_list is not None
        assert len(event.todo_list) == 3
        assert event.todo_list[0].content == "Write tests"
        assert event.todo_list[0].status == "completed"
        assert event.todo_list[1].status == "in_progress"
        assert event.todo_list[1].active_form == "Implementing feature"
        assert event.todo_list[2].status == "pending"

    def test_todo_write_skips_empty_content(self):
        todos = [
            {"content": "", "status": "pending"},
            {"content": "Real task", "status": "pending"},
        ]
        event = parse_line(self._make_todo_line(todos))
        assert event is not None
        assert event.todo_list is not None
        assert len(event.todo_list) == 1
        assert event.todo_list[0].content == "Real task"

    def test_todo_write_empty_list(self):
        event = parse_line(self._make_todo_line([]))
        assert event is not None
        assert event.todo_list == []

    def test_todo_write_missing_active_form(self):
        todos = [{"content": "Task", "status": "in_progress"}]
        event = parse_line(self._make_todo_line(todos))
        assert event is not None
        assert event.todo_list is not None
        assert event.todo_list[0].active_form == ""

    def test_exit_plan_mode_sets_is_plan_approval(self):
        import json

        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "plan-1",
                            "name": "ExitPlanMode",
                            "input": {},
                        }
                    ]
                },
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.is_plan_approval is True

    def test_permission_request_parsed(self):
        import json

        line = json.dumps(
            {
                "type": "system",
                "subtype": "permission_request",
                "request_id": "req-1",
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /tmp/test"},
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.permission_request is not None
        assert event.permission_request.request_id == "req-1"
        assert event.permission_request.tool_name == "Bash"
        assert event.permission_request.tool_input == {"command": "rm -rf /tmp/test"}

    def test_elicitation_parsed(self):
        import json

        line = json.dumps(
            {
                "type": "system",
                "subtype": "elicitation",
                "request_id": "elic-1",
                "server_name": "my-mcp-server",
                "mode": "form-mode",
                "message": "Please fill in the form",
                "schema": {"type": "object", "properties": {"name": {"type": "string"}}},
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.elicitation is not None
        assert event.elicitation.request_id == "elic-1"
        assert event.elicitation.server_name == "my-mcp-server"
        assert event.elicitation.mode == "form-mode"
        assert event.elicitation.message == "Please fill in the form"
