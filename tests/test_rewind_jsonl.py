"""Tests for claude_discord.claude.rewind — pure JSONL utility functions."""

from __future__ import annotations

import json
from pathlib import Path

from claude_discord.claude.rewind import (
    _cwd_to_project_dir,
    _extract_text,
    find_session_jsonl,
    parse_user_turns,
    truncate_jsonl_at_line,
)

# ---------------------------------------------------------------------------
# _cwd_to_project_dir
# ---------------------------------------------------------------------------


def test_cwd_to_project_dir_simple() -> None:
    assert _cwd_to_project_dir("/home/ebi") == "-home-ebi"


def test_cwd_to_project_dir_nested() -> None:
    assert _cwd_to_project_dir("/home/ebi/my-repo") == "-home-ebi-my-repo"


def test_cwd_to_project_dir_underscores() -> None:
    assert _cwd_to_project_dir("/home/ebi/foo_bar") == "-home-ebi-foo-bar"


def test_cwd_to_project_dir_mixed() -> None:
    assert _cwd_to_project_dir("/home/ebi/foo_bar/baz-qux") == "-home-ebi-foo-bar-baz-qux"


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------


def test_extract_text_string() -> None:
    assert _extract_text("hello world") == "hello world"


def test_extract_text_list_of_blocks() -> None:
    content = [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]
    assert _extract_text(content) == "hello world"


def test_extract_text_list_with_non_text_blocks() -> None:
    content = [{"type": "image", "url": "http://..."}, {"type": "text", "text": "hi"}]
    assert _extract_text(content) == "hi"


def test_extract_text_empty_string() -> None:
    assert _extract_text("") == ""


def test_extract_text_non_string_non_list() -> None:
    assert _extract_text(None) == ""
    assert _extract_text(42) == ""


# ---------------------------------------------------------------------------
# parse_user_turns
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    """Write a list of dicts as a JSONL file."""
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def test_parse_user_turns_basic(tmp_path: Path) -> None:
    jsonl = tmp_path / "sess.jsonl"
    _write_jsonl(
        jsonl,
        [
            {
                "type": "user",
                "uuid": "u1",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "Hello Claude"},
            },
            {
                "type": "assistant",
                "uuid": "a1",
                "message": {"content": "Hello!"},
            },
            {
                "type": "user",
                "uuid": "u2",
                "timestamp": "2026-01-01T00:01:00Z",
                "message": {"content": "What is 2+2?"},
            },
        ],
    )
    turns = parse_user_turns(jsonl)
    assert len(turns) == 2
    assert turns[0].text == "Hello Claude"
    assert turns[0].line_index == 0
    assert turns[1].text == "What is 2+2?"
    assert turns[1].line_index == 2


def test_parse_user_turns_skips_meta(tmp_path: Path) -> None:
    jsonl = tmp_path / "sess.jsonl"
    _write_jsonl(
        jsonl,
        [
            {
                "type": "user",
                "isMeta": True,
                "uuid": "m1",
                "message": {"content": "some meta"},
            },
            {
                "type": "user",
                "uuid": "u1",
                "message": {"content": "real message"},
            },
        ],
    )
    turns = parse_user_turns(jsonl)
    assert len(turns) == 1
    assert turns[0].text == "real message"


def test_parse_user_turns_skips_xml_prefixed(tmp_path: Path) -> None:
    jsonl = tmp_path / "sess.jsonl"
    _write_jsonl(
        jsonl,
        [
            {
                "type": "user",
                "uuid": "x1",
                "message": {"content": "<context>internal stuff</context>"},
            },
            {
                "type": "user",
                "uuid": "u1",
                "message": {"content": "normal message"},
            },
        ],
    )
    turns = parse_user_turns(jsonl)
    assert len(turns) == 1
    assert turns[0].text == "normal message"


def test_parse_user_turns_respects_max_turns(tmp_path: Path) -> None:
    jsonl = tmp_path / "sess.jsonl"
    entries = [
        {"type": "user", "uuid": f"u{i}", "message": {"content": f"message {i}"}} for i in range(30)
    ]
    _write_jsonl(jsonl, entries)
    turns = parse_user_turns(jsonl, max_turns=5)
    assert len(turns) == 5
    # Should be the last 5 entries
    assert turns[0].text == "message 25"
    assert turns[-1].text == "message 29"


def test_parse_user_turns_empty_file(tmp_path: Path) -> None:
    jsonl = tmp_path / "empty.jsonl"
    jsonl.write_text("")
    turns = parse_user_turns(jsonl)
    assert turns == []


def test_parse_user_turns_missing_file(tmp_path: Path) -> None:
    jsonl = tmp_path / "nonexistent.jsonl"
    turns = parse_user_turns(jsonl)
    assert turns == []


def test_parse_user_turns_preserves_line_index(tmp_path: Path) -> None:
    """line_index must point to the actual line in the file."""
    jsonl = tmp_path / "sess.jsonl"
    entries = [
        {"type": "assistant", "uuid": "a0", "message": {"content": "intro"}},
        {"type": "user", "uuid": "u1", "message": {"content": "first user msg"}},
        {"type": "assistant", "uuid": "a1", "message": {"content": "response"}},
        {"type": "user", "uuid": "u2", "message": {"content": "second user msg"}},
    ]
    _write_jsonl(jsonl, entries)
    turns = parse_user_turns(jsonl)
    assert turns[0].line_index == 1  # "first user msg" is on line index 1
    assert turns[1].line_index == 3  # "second user msg" is on line index 3


def test_parse_user_turns_list_content(tmp_path: Path) -> None:
    """Content given as a list of text blocks should be extracted correctly."""
    jsonl = tmp_path / "sess.jsonl"
    _write_jsonl(
        jsonl,
        [
            {
                "type": "user",
                "uuid": "u1",
                "message": {"content": [{"type": "text", "text": "block message"}]},
            }
        ],
    )
    turns = parse_user_turns(jsonl)
    assert len(turns) == 1
    assert turns[0].text == "block message"


# ---------------------------------------------------------------------------
# truncate_jsonl_at_line
# ---------------------------------------------------------------------------


def test_truncate_jsonl_removes_selected_and_after(tmp_path: Path) -> None:
    jsonl = tmp_path / "sess.jsonl"
    lines = [
        '{"type":"user","message":{"content":"turn 0"}}\n',
        '{"type":"assistant","message":{"content":"resp 0"}}\n',
        '{"type":"user","message":{"content":"turn 1"}}\n',
        '{"type":"assistant","message":{"content":"resp 1"}}\n',
    ]
    jsonl.write_text("".join(lines))

    result = truncate_jsonl_at_line(jsonl, line_index=2)

    assert result is True
    remaining = jsonl.read_text().splitlines()
    assert len(remaining) == 2
    assert "turn 0" in remaining[0]
    assert "resp 0" in remaining[1]


def test_truncate_jsonl_at_zero_empties_file(tmp_path: Path) -> None:
    jsonl = tmp_path / "sess.jsonl"
    jsonl.write_text('{"type":"user","message":{"content":"only"}}\n')

    result = truncate_jsonl_at_line(jsonl, line_index=0)

    assert result is True
    assert jsonl.read_text() == ""


def test_truncate_jsonl_returns_false_on_missing_file(tmp_path: Path) -> None:
    jsonl = tmp_path / "nonexistent.jsonl"
    result = truncate_jsonl_at_line(jsonl, line_index=1)
    assert result is False


def test_truncate_jsonl_beyond_end_keeps_all(tmp_path: Path) -> None:
    """Truncating beyond the last line keeps the file intact."""
    jsonl = tmp_path / "sess.jsonl"
    content = '{"type":"user","message":{"content":"only"}}\n'
    jsonl.write_text(content)

    result = truncate_jsonl_at_line(jsonl, line_index=999)

    assert result is True
    assert jsonl.read_text() == content


# ---------------------------------------------------------------------------
# find_session_jsonl
# ---------------------------------------------------------------------------


def test_find_session_jsonl_via_working_dir(tmp_path: Path, monkeypatch) -> None:
    """Should find the JSONL at the expected path when working_dir matches."""
    import claude_code_core.rewind as core_rewind_mod

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(core_rewind_mod, "_CLAUDE_PROJECTS_DIR", projects_dir)

    project_dir = projects_dir / "-home-ebi-myrepo"
    project_dir.mkdir()
    session_id = "abc123"
    jsonl = project_dir / f"{session_id}.jsonl"
    jsonl.write_text("")

    result = find_session_jsonl(session_id, "/home/ebi/myrepo")
    assert result == jsonl


def test_find_session_jsonl_fallback_search(tmp_path: Path, monkeypatch) -> None:
    """Should find the JSONL via glob fallback when working_dir doesn't match."""
    import claude_code_core.rewind as core_rewind_mod

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(core_rewind_mod, "_CLAUDE_PROJECTS_DIR", projects_dir)

    other_dir = projects_dir / "-some-other-dir"
    other_dir.mkdir()
    session_id = "xyz789"
    jsonl = other_dir / f"{session_id}.jsonl"
    jsonl.write_text("")

    # Pass working_dir that doesn't match
    result = find_session_jsonl(session_id, "/does/not/exist")
    assert result == jsonl


def test_find_session_jsonl_returns_none_when_not_found(tmp_path: Path, monkeypatch) -> None:
    import claude_code_core.rewind as core_rewind_mod

    monkeypatch.setattr(core_rewind_mod, "_CLAUDE_PROJECTS_DIR", tmp_path / "empty")

    result = find_session_jsonl("no-such-session", "/some/dir")
    assert result is None
