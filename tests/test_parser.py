"""Tests for stream-json parser."""

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
