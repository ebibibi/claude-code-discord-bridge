---
name: test-guide
description: Testing patterns for claude-discord — pytest, async testing, mocking Discord objects, TDD workflow
---

# Test Guide — Testing Patterns for claude-discord

## When to Activate

- Writing tests for new features
- Fixing test failures
- Adding test coverage for existing code
- When asked to "add tests", "test this", or "improve coverage"

## TDD Workflow

Follow the Red-Green-Refactor cycle:

1. **RED**: Write a failing test that describes the desired behavior
2. **GREEN**: Write the minimum code to make the test pass
3. **REFACTOR**: Clean up while keeping tests green

## Project Test Setup

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- **pytest-asyncio**: Auto mode — all async test functions run automatically
- **pytest-cov**: Coverage reporting
- **No test markers needed**: asyncio_mode = "auto" handles async tests

## Test Patterns by Module

### Pure Logic (parser, chunker, types) — Full Unit Tests

These have no external dependencies. Test exhaustively:

```python
def test_parse_system_message():
    line = '{"type":"system","session_id":"abc-123"}'
    event = parse_line(line)
    assert event.message_type == MessageType.SYSTEM
    assert event.session_id == "abc-123"

def test_parse_invalid_json():
    event = parse_line("not json")
    assert event is None
```

### Repository (database) — Integration Tests with Real SQLite

```python
@pytest.fixture
async def repo(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    return SessionRepository(db_path)

async def test_save_and_get(repo):
    await repo.save(thread_id=123, session_id="abc-def")
    result = await repo.get_session_id(thread_id=123)
    assert result == "abc-def"
```

### Runner — Unit Test Args/Env Building

```python
def test_build_args_basic():
    runner = ClaudeRunner(command="claude", model="sonnet")
    args = runner._build_args("hello", session_id=None)
    assert args[0] == "claude"
    assert "-p" in args
    assert "--" in args
    assert args[-1] == "hello"

def test_build_args_rejects_invalid_session():
    runner = ClaudeRunner()
    with pytest.raises(ValueError):
        runner._build_args("hello", session_id="'; DROP TABLE --")

def test_env_strips_secrets():
    runner = ClaudeRunner()
    import os
    os.environ["DISCORD_BOT_TOKEN"] = "test-token"
    env = runner._build_env()
    assert "DISCORD_BOT_TOKEN" not in env
```

### Cogs — Mock Discord Objects

```python
from unittest.mock import AsyncMock, MagicMock

def make_mock_interaction(user_id: int = 12345) -> MagicMock:
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.id = user_id
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    return interaction
```

### Chunker — Edge Cases Are Critical

```python
def test_chunk_empty_string():
    assert chunk_message("") == []

def test_chunk_preserves_code_blocks():
    text = "```python\nprint('hello')\n```"
    chunks = chunk_message(text)
    assert len(chunks) == 1

def test_chunk_splits_at_boundary():
    long_text = "a" * 3000
    chunks = chunk_message(long_text)
    assert all(len(c) <= 2000 for c in chunks)
```

## Running Tests

```bash
# Full suite with coverage
uv run pytest tests/ -v --cov=claude_discord --cov-report=term-missing

# Single file
uv run pytest tests/test_parser.py -v

# Single test
uv run pytest tests/test_parser.py::test_parse_system_message -v

# Stop on first failure
uv run pytest tests/ -x
```

## Coverage Goals

- **Parser, chunker, types**: 90%+ (pure logic, easy to test)
- **Repository**: 90%+ (real SQLite, no mocks needed)
- **Runner**: 60%+ (test arg building and env, mock subprocess)
- **Cogs, StatusManager**: 30%+ (heavy Discord mocking, test validation logic)
- **Overall**: 50%+ and improving

## What NOT to Test

- Discord.py library internals
- SQLite behavior
- asyncio internals
- Simple property access / getters
