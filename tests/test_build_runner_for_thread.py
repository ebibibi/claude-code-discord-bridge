"""Tests for ClaudeChatCog._build_runner_for_thread.

Verifies backend-aware resolution, model precedence rules, fallback to
legacy clone() when factory/settings are missing, and that overrides
do not leak between backends (e.g. Claude model "opus" should not be
passed through to a Codex spawn).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import aiosqlite

from claude_code_core.codex_runner import CodexRunner
from claude_code_core.runner import ClaudeRunner
from claude_discord.backend_factory import BackendFactory
from claude_discord.backend_settings import BackendSettings
from claude_discord.database.settings_repo import SettingsRepository


async def _new_settings_repo() -> SettingsRepository:
    tmp = Path(tempfile.mkdtemp()) / "settings.db"
    async with aiosqlite.connect(str(tmp)) as db:
        await db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        await db.commit()
    return SettingsRepository(str(tmp))


def _factory() -> BackendFactory:
    return BackendFactory(
        claude_command="claude",
        codex_command="codex",
        permission_mode="acceptEdits",
        working_dir=None,
        timeout_seconds=300,
        dangerously_skip_permissions=False,
        allowed_tools=None,
        append_system_prompt=None,
        effort=None,
    )


def _cog(*, factory: BackendFactory | None, settings: BackendSettings | None):
    """Minimal stand-in for ClaudeChatCog that exposes _build_runner_for_thread."""
    from claude_discord.cogs.claude_chat import ClaudeChatCog

    # Skip the real __init__ — we only need the method bound to a mock self.
    cog = ClaudeChatCog.__new__(ClaudeChatCog)
    cog._factory = factory  # type: ignore[attr-defined]
    cog._backend_settings = settings  # type: ignore[attr-defined]
    # Provide a runner so the legacy fallback path is exercisable.
    cog.runner = ClaudeRunner(command="claude", model="sonnet")  # type: ignore[attr-defined]
    return cog


class TestBuildRunnerLegacyFallback:
    """Without factory + settings, must call self.runner.clone()."""

    async def test_legacy_clone_called(self) -> None:
        cog = _cog(factory=None, settings=None)
        # Replace .runner with a magic mock so we can capture the clone call.
        cog.runner = MagicMock()
        cog.runner.clone.return_value = "CLONED"
        result = await cog._build_runner_for_thread(
            thread_id=42,
            model_override=None,
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override=None,
        )
        assert result == "CLONED"
        cog.runner.clone.assert_called_once()


class TestBuildRunnerBackendResolution:
    async def test_global_claude_default(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=1,
            model_override=None,
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override=None,
        )
        assert isinstance(runner, ClaudeRunner)
        assert runner.model == "sonnet"

    async def test_thread_override_codex_returns_codex_runner(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await settings.set_backend("codex", thread_id=99)
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=99,
            model_override=None,
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override=None,
        )
        # The thread override pins backend=codex, so we should get a CodexRunner.
        assert isinstance(runner, CodexRunner)
        # No stored model for codex → defer to the Codex CLI's own default
        # (omit --model) rather than pinning a stale version.
        assert runner.model is None

    async def test_other_thread_keeps_global(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await settings.set_backend("codex", thread_id=99)  # thread 99 only
        cog = _cog(factory=_factory(), settings=settings)
        # Thread 1 should still use global default (claude).
        runner = await cog._build_runner_for_thread(
            thread_id=1,
            model_override=None,
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override=None,
        )
        assert isinstance(runner, ClaudeRunner)

    async def test_global_codex_then_thread_keeps_codex(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await settings.set_backend("codex")  # global
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=123,
            model_override=None,
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override=None,
        )
        assert isinstance(runner, CodexRunner)


class TestBuildRunnerModelResolution:
    """The key regression: a stale Claude /model-set value MUST NOT leak
    through to a Codex spawn, or codex CLI rejects the model name."""

    async def test_legacy_model_override_does_not_leak_to_codex(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await settings.set_backend("codex", thread_id=7)
        cog = _cog(factory=_factory(), settings=settings)
        # User previously did /model-set opus while on claude. That value is
        # passed as `model_override`. When the thread's backend is codex we
        # must IGNORE it and defer to the Codex CLI's own default (model=None).
        runner = await cog._build_runner_for_thread(
            thread_id=7,
            model_override="opus",
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override=None,
        )
        assert isinstance(runner, CodexRunner)
        assert runner.model is None, "Claude model 'opus' must not leak through to a Codex spawn"

    async def test_legacy_model_override_is_used_for_claude(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=1,
            model_override="opus",
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override=None,
        )
        assert isinstance(runner, ClaudeRunner)
        assert runner.model == "opus"

    async def test_per_backend_stored_model_takes_priority(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await settings.set_backend("codex", thread_id=5)
        # User explicitly set codex model via /model command for this thread.
        await settings.set_model("codex", "o4-mini", thread_id=5)
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=5,
            model_override="opus",  # legacy /model-set leftover — should be ignored
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override=None,
        )
        assert isinstance(runner, CodexRunner)
        assert runner.model == "o4-mini"


class TestBuildRunnerPerCallOverrides:
    async def test_allowed_tools_applied(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=1,
            model_override=None,
            tools_override=["Read", "Glob"],
            fork_session=False,
            working_dir_override=None,
            effort_override=None,
        )
        assert runner.allowed_tools == ["Read", "Glob"]

    async def test_working_dir_applied(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=1,
            model_override=None,
            tools_override=None,
            fork_session=False,
            working_dir_override="/work",
            effort_override=None,
        )
        assert runner.working_dir == "/work"

    async def test_effort_only_on_claude(self) -> None:
        """Codex doesn't expose .effort; the helper must not set it."""
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await settings.set_backend("codex", thread_id=11)
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=11,
            model_override=None,
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override="high",
        )
        # The legacy claude effort_override must NOT leak onto a Codex spawn
        # (Codex effort levels differ from Claude's).
        assert isinstance(runner, CodexRunner)
        assert getattr(runner, "effort", None) is None


class TestBuildRunnerPerBackendEffort:
    """Per-backend effort from BackendSettings is applied at spawn time."""

    async def test_codex_effort_from_settings_applied(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await settings.set_backend("codex", thread_id=21)
        await settings.set_effort("codex", "xhigh", thread_id=21)
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=21,
            model_override=None,
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override=None,
        )
        assert isinstance(runner, CodexRunner)
        assert runner.effort == "xhigh"
        assert "model_reasoning_effort=xhigh" in runner._build_args("hi", session_id=None)

    async def test_claude_effort_from_settings_overrides_legacy(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        await settings.set_effort("claude", "max")
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=1,
            model_override=None,
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override="low",  # legacy /effort-set value, lower precedence
        )
        assert isinstance(runner, ClaudeRunner)
        assert runner.effort == "max"

    async def test_claude_legacy_effort_still_applies_when_no_setting(self) -> None:
        repo = await _new_settings_repo()
        settings = BackendSettings(
            repo,
            env_backend="claude",
            env_model_for_claude="sonnet",
            env_model_for_codex="",
        )
        cog = _cog(factory=_factory(), settings=settings)
        runner = await cog._build_runner_for_thread(
            thread_id=1,
            model_override=None,
            tools_override=None,
            fork_session=False,
            working_dir_override=None,
            effort_override="high",
        )
        assert isinstance(runner, ClaudeRunner)
        assert runner.effort == "high"
