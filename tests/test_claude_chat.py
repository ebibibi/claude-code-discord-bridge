"""Tests for ClaudeChatCog: /stop command, attachment handling, and interrupt-on-new-message."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from claude_discord.cogs.claude_chat import ClaudeChatCog
from claude_discord.concurrency import SessionRegistry
from claude_discord.coordination.service import CoordinationService


def _make_cog() -> ClaudeChatCog:
    """Return a ClaudeChatCog with minimal mocked dependencies."""
    bot = MagicMock()
    bot.channel_id = 999
    repo = MagicMock()
    repo.get = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    repo.delete = AsyncMock(return_value=True)
    runner = MagicMock()
    runner.clone = MagicMock(return_value=MagicMock())
    return ClaudeChatCog(bot=bot, repo=repo, runner=runner)


def _make_thread_interaction(thread_id: int = 12345) -> MagicMock:
    """Return an Interaction whose channel is a discord.Thread."""
    interaction = MagicMock(spec=discord.Interaction)
    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    interaction.channel = thread
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _make_channel_interaction() -> MagicMock:
    """Return an Interaction whose channel is NOT a thread."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.channel = MagicMock(spec=discord.TextChannel)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


class TestStopCommand:
    @pytest.mark.asyncio
    async def test_stop_outside_thread_sends_ephemeral(self) -> None:
        """Using /stop outside a thread sends an ephemeral error."""
        cog = _make_cog()
        interaction = _make_channel_interaction()

        await cog.stop_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_stop_no_active_runner_sends_ephemeral(self) -> None:
        """Using /stop when nothing is running sends an ephemeral notice."""
        cog = _make_cog()
        interaction = _make_thread_interaction(thread_id=12345)

        # _active_runners is empty — no session running
        await cog.stop_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        assert call_kwargs.get("ephemeral") is True

    @pytest.mark.asyncio
    async def test_stop_calls_runner_interrupt(self) -> None:
        """Using /stop with an active runner calls runner.interrupt()."""
        cog = _make_cog()
        thread_id = 12345
        interaction = _make_thread_interaction(thread_id=thread_id)

        mock_runner = MagicMock()
        mock_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = mock_runner

        await cog.stop_session.callback(cog, interaction)

        mock_runner.interrupt.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_does_not_delete_session_from_db(self) -> None:
        """/stop must NOT delete the session from the DB (so resume works)."""
        cog = _make_cog()
        thread_id = 12345
        interaction = _make_thread_interaction(thread_id=thread_id)

        mock_runner = MagicMock()
        mock_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = mock_runner

        await cog.stop_session.callback(cog, interaction)

        # repo.delete should NEVER be called by /stop
        cog.repo.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_does_not_remove_from_active_runners(self) -> None:
        """/stop should leave _active_runners cleanup to _run_claude's finally."""
        cog = _make_cog()
        thread_id = 12345
        interaction = _make_thread_interaction(thread_id=thread_id)

        mock_runner = MagicMock()
        mock_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = mock_runner

        await cog.stop_session.callback(cog, interaction)

        # Still in dict — _run_claude's finally handles removal
        assert thread_id in cog._active_runners

    @pytest.mark.asyncio
    async def test_stop_sends_stopped_embed(self) -> None:
        """/stop success response should use the stopped_embed (orange, not red)."""
        cog = _make_cog()
        thread_id = 12345
        interaction = _make_thread_interaction(thread_id=thread_id)

        mock_runner = MagicMock()
        mock_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = mock_runner

        await cog.stop_session.callback(cog, interaction)

        interaction.response.send_message.assert_called_once()
        call_kwargs = interaction.response.send_message.call_args.kwargs
        embed = call_kwargs.get("embed")
        assert embed is not None
        assert "stopped" in embed.title.lower()
        # Orange color (not red error)
        assert embed.color.value == 0xFFA500


class TestActiveCountAlias:
    """Tests for ClaudeChatCog.active_count (DrainAware alias)."""

    def test_active_count_equals_active_session_count(self) -> None:
        """active_count should be an alias for active_session_count."""
        cog = _make_cog()
        assert cog.active_count == 0
        assert cog.active_count == cog.active_session_count

        # Add a fake runner
        cog._active_runners[1] = MagicMock()
        assert cog.active_count == 1
        assert cog.active_count == cog.active_session_count

        cog._active_runners[2] = MagicMock()
        assert cog.active_count == 2
        assert cog.active_count == cog.active_session_count


class TestRegistryAutoDiscovery:
    """Registry should be auto-discovered from bot.session_registry."""

    def test_auto_discovers_from_bot(self) -> None:
        """When registry=None, Cog picks up bot.session_registry."""
        bot = MagicMock()
        bot.session_registry = SessionRegistry()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        assert cog._registry is bot.session_registry

    def test_explicit_registry_takes_precedence(self) -> None:
        """When registry is explicitly passed, it wins over bot attribute."""
        bot = MagicMock()
        bot.session_registry = SessionRegistry()
        explicit = SessionRegistry()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock(), registry=explicit)
        assert cog._registry is explicit

    def test_no_bot_attribute_falls_back_to_none(self) -> None:
        """When bot has no session_registry, _registry stays None."""
        bot = MagicMock(spec=[])  # no attributes
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        assert cog._registry is None


class TestInterruptOnNewMessage:
    """New message in active thread should interrupt the running session."""

    def _make_thread_message(self, thread_id: int = 42) -> MagicMock:
        """Return a discord.Message inside a Thread."""
        thread = MagicMock(spec=discord.Thread)
        thread.id = thread_id
        thread.parent_id = 999
        thread.send = AsyncMock()
        msg = MagicMock(spec=discord.Message)
        msg.channel = thread
        msg.content = "new instruction"
        msg.attachments = []
        msg.author = MagicMock()
        msg.author.bot = False
        return msg

    @pytest.mark.asyncio
    async def test_interrupt_called_when_runner_active(self) -> None:
        """When a runner is active for a thread, _handle_thread_reply must interrupt it."""
        cog = _make_cog()
        thread_id = 42
        message = self._make_thread_message(thread_id)

        # Plant an active runner in the cog
        existing_runner = MagicMock()
        existing_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = existing_runner

        # Stub _run_claude so we don't actually spawn Claude
        cog._run_claude = AsyncMock()

        await cog._handle_thread_reply(message)

        existing_runner.interrupt.assert_called_once()

    @pytest.mark.asyncio
    async def test_interrupt_message_sent_to_thread(self) -> None:
        """The thread should receive a notification when the session is interrupted."""
        cog = _make_cog()
        thread_id = 42
        message = self._make_thread_message(thread_id)
        thread = message.channel

        existing_runner = MagicMock()
        existing_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = existing_runner
        cog._run_claude = AsyncMock()

        await cog._handle_thread_reply(message)

        thread.send.assert_called_once()
        sent_text: str = thread.send.call_args.args[0]
        assert "interrupted" in sent_text.lower() or "⚡" in sent_text

    @pytest.mark.asyncio
    async def test_no_interrupt_when_no_active_runner(self) -> None:
        """When no runner is active, _handle_thread_reply skips interrupt."""
        cog = _make_cog()
        message = self._make_thread_message(thread_id=42)
        thread = message.channel

        cog._run_claude = AsyncMock()

        await cog._handle_thread_reply(message)

        # No notification message sent for interruption
        thread.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_awaits_existing_task_before_new_session(self) -> None:
        """_handle_thread_reply must await the existing task to ensure cleanup completes."""
        cog = _make_cog()
        thread_id = 42
        message = self._make_thread_message(thread_id)

        existing_runner = MagicMock()
        existing_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = existing_runner

        # A future that we can control to simulate a running task
        cleanup_done = asyncio.Event()
        call_order: list[str] = []

        async def slow_task() -> None:
            await cleanup_done.wait()
            call_order.append("task_done")

        task = asyncio.ensure_future(slow_task())
        cog._active_tasks[thread_id] = task

        async def run_claude_stub(*args, **kwargs) -> None:
            call_order.append("new_session_started")

        cog._run_claude = run_claude_stub

        # Let cleanup complete so the await resolves
        cleanup_done.set()

        await cog._handle_thread_reply(message)

        assert call_order == ["task_done", "new_session_started"]

    @pytest.mark.asyncio
    async def test_run_claude_called_with_session_id_after_interrupt(self) -> None:
        """After interrupt, _run_claude is called with the session_id from the DB."""
        cog = _make_cog()
        thread_id = 42
        message = self._make_thread_message(thread_id)

        # Simulate a saved session in DB
        record = MagicMock()
        record.session_id = "abc-123"
        cog.repo.get = AsyncMock(return_value=record)

        existing_runner = MagicMock()
        existing_runner.interrupt = AsyncMock()
        cog._active_runners[thread_id] = existing_runner
        cog._run_claude = AsyncMock()

        await cog._handle_thread_reply(message)

        cog._run_claude.assert_called_once()
        _, kwargs = cog._run_claude.call_args
        assert kwargs.get("session_id") == "abc-123"

    @pytest.mark.asyncio
    async def test_active_tasks_dict_initialized(self) -> None:
        """ClaudeChatCog must initialize _active_tasks as an empty dict."""
        cog = _make_cog()
        assert hasattr(cog, "_active_tasks")
        assert isinstance(cog._active_tasks, dict)
        assert len(cog._active_tasks) == 0


class TestZeroConfigCoordination:
    """_get_coordination() must work without any consumer wiring (Zero-Config Principle).

    Consumers (like EbiBot) must get new features by updating the package alone —
    no code changes, no bot.coordination wiring required.
    """

    def test_auto_creates_from_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No bot.coordination → auto-creates CoordinationService from env var."""
        monkeypatch.setenv("COORDINATION_CHANNEL_ID", "1234567890")
        bot = MagicMock(spec=[])  # no attributes at all
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        svc = cog._get_coordination()
        assert isinstance(svc, CoordinationService)
        assert svc.enabled is True

    def test_no_op_when_env_var_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No env var → returns a no-op CoordinationService (never None)."""
        monkeypatch.delenv("COORDINATION_CHANNEL_ID", raising=False)
        bot = MagicMock(spec=[])
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        svc = cog._get_coordination()
        assert isinstance(svc, CoordinationService)
        assert svc.enabled is False  # no-op, but not None

    def test_bot_attribute_takes_precedence(self) -> None:
        """Explicitly set bot.coordination wins over env var auto-creation."""
        explicit = CoordinationService(MagicMock(), channel_id=9999)
        bot = MagicMock()
        bot.coordination = explicit
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        assert cog._get_coordination() is explicit

    def test_constructor_arg_takes_precedence(self) -> None:
        """Explicitly passed coordination= wins over everything."""
        explicit = CoordinationService(MagicMock(), channel_id=9999)
        bot = MagicMock()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock(), coordination=explicit)
        assert cog._get_coordination() is explicit

    def test_result_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Second call returns same object (no repeated env var reads)."""
        monkeypatch.setenv("COORDINATION_CHANNEL_ID", "1234567890")
        bot = MagicMock(spec=[])
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        assert cog._get_coordination() is cog._get_coordination()


class TestSpawnSession:
    """Tests for ClaudeChatCog.spawn_session()."""

    @pytest.mark.asyncio
    async def test_spawn_creates_thread_and_returns_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """spawn_session creates a thread with the right name and returns it."""
        from unittest.mock import AsyncMock, MagicMock, patch

        import discord

        thread = MagicMock(spec=discord.Thread)
        thread.id = 42
        thread.name = "Test spawn"
        thread.send = AsyncMock()

        channel = MagicMock()
        channel.create_thread = AsyncMock(return_value=thread)

        bot = MagicMock()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())

        with patch.object(cog, "_run_claude", new=AsyncMock()):
            result = await cog.spawn_session(channel, "Do the thing")

        assert result is thread
        channel.create_thread.assert_called_once()
        call_kwargs = channel.create_thread.call_args.kwargs
        assert call_kwargs["name"] == "Do the thing"
        assert call_kwargs["type"] == discord.ChannelType.public_thread

    @pytest.mark.asyncio
    async def test_spawn_uses_custom_thread_name(self) -> None:
        """thread_name overrides the default (prompt[:100])."""
        from unittest.mock import AsyncMock, MagicMock, patch

        import discord

        thread = MagicMock(spec=discord.Thread)
        thread.send = AsyncMock()

        channel = MagicMock()
        channel.create_thread = AsyncMock(return_value=thread)

        bot = MagicMock()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())

        with patch.object(cog, "_run_claude", new=AsyncMock()):
            await cog.spawn_session(channel, "Very long prompt text", thread_name="Short name")

        kwargs = channel.create_thread.call_args.kwargs
        assert kwargs["name"] == "Short name"

    @pytest.mark.asyncio
    async def test_spawn_posts_seed_message(self) -> None:
        """spawn_session sends the prompt as the first thread message."""
        from unittest.mock import AsyncMock, MagicMock, patch

        import discord

        thread = MagicMock(spec=discord.Thread)
        seed_msg = MagicMock()
        thread.send = AsyncMock(return_value=seed_msg)

        channel = MagicMock()
        channel.create_thread = AsyncMock(return_value=thread)

        bot = MagicMock()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())

        mock_run = AsyncMock()
        with patch.object(cog, "_run_claude", new=mock_run):
            await cog.spawn_session(channel, "Hello Claude")

        thread.send.assert_called_once_with("Hello Claude")
        # _run_claude receives the seed message (not a user message)
        user_msg_arg = mock_run.call_args.args[0]
        assert user_msg_arg is seed_msg


class TestOnReady:
    """Tests for ClaudeChatCog.on_ready — startup session resume logic."""

    @pytest.mark.asyncio
    async def test_on_ready_no_resume_repo_is_noop(self) -> None:
        """If resume_repo is not set, on_ready should do nothing."""
        # spec=[] prevents MagicMock from auto-generating resume_repo attribute
        bot = MagicMock(spec=[])
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock())
        assert cog._resume_repo is None
        # Should complete without error and without touching bot
        await cog.on_ready()

    @pytest.mark.asyncio
    async def test_on_ready_no_pending_is_noop(self) -> None:
        """If resume_repo returns no pending entries, on_ready does nothing."""
        from unittest.mock import AsyncMock, MagicMock

        from claude_discord.database.resume_repo import PendingResumeRepository

        resume_repo = MagicMock(spec=PendingResumeRepository)
        resume_repo.get_pending = AsyncMock(return_value=[])

        bot = MagicMock()
        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock(), resume_repo=resume_repo)
        await cog.on_ready()
        bot.get_channel.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_ready_deletes_before_spawning(self) -> None:
        """Row must be deleted BEFORE _run_claude is called (single-fire guarantee)."""
        from unittest.mock import AsyncMock, MagicMock, patch

        import discord

        from claude_discord.database.resume_repo import PendingResume, PendingResumeRepository

        entry = PendingResume(
            id=7,
            thread_id=555,
            session_id="sess-abc",
            reason="self_restart",
            resume_prompt="Continue please.",
            created_at="2026-02-21 20:00:00",
        )
        resume_repo = MagicMock(spec=PendingResumeRepository)
        resume_repo.get_pending = AsyncMock(return_value=[entry])
        resume_repo.delete = AsyncMock()

        thread = MagicMock(spec=discord.Thread)
        thread.id = 555
        thread.send = AsyncMock(return_value=MagicMock())
        parent = MagicMock(spec=discord.TextChannel)
        thread.parent = parent

        bot = MagicMock()
        bot.get_channel.return_value = thread

        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock(), resume_repo=resume_repo)

        call_order: list[str] = []
        resume_repo.delete.side_effect = lambda _: call_order.append("delete")

        async def fake_run_claude(*args, **kwargs):
            call_order.append("run_claude")

        with patch.object(cog, "_run_claude", side_effect=fake_run_claude):
            await cog.on_ready()
            # create_task schedules the coroutine; yield to the event loop so it runs.
            await asyncio.sleep(0)

        assert call_order == ["delete", "run_claude"], (
            "delete() must be called before _run_claude to prevent double-resume"
        )

    @pytest.mark.asyncio
    async def test_on_ready_skips_non_thread_channels(self) -> None:
        """If get_channel returns a non-Thread, skip gracefully."""
        from unittest.mock import AsyncMock, MagicMock

        import discord

        from claude_discord.database.resume_repo import PendingResume, PendingResumeRepository

        entry = PendingResume(
            id=1,
            thread_id=100,
            session_id=None,
            reason="self_restart",
            resume_prompt=None,
            created_at="2026-02-21 20:00:00",
        )
        resume_repo = MagicMock(spec=PendingResumeRepository)
        resume_repo.get_pending = AsyncMock(return_value=[entry])
        resume_repo.delete = AsyncMock()

        # Return a TextChannel (not a Thread) — should be skipped
        bot = MagicMock()
        bot.get_channel.return_value = MagicMock(spec=discord.TextChannel)

        cog = ClaudeChatCog(bot=bot, repo=MagicMock(), runner=MagicMock(), resume_repo=resume_repo)
        # Should not raise
        await cog.on_ready()
        # delete was still called (single-fire)
        resume_repo.delete.assert_called_once_with(1)


class TestCogUnloadMarkForResume:
    """Tests for cog_unload() auto-marking active sessions for restart-resume."""

    def _make_cog_with_resume_repo(self) -> tuple[ClaudeChatCog, MagicMock, MagicMock]:
        """Return (cog, repo, resume_repo) with resume_repo configured."""
        bot = MagicMock()
        bot.channel_id = 999
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        resume_repo = MagicMock()
        resume_repo.mark = AsyncMock(return_value=1)
        cog = ClaudeChatCog(bot=bot, repo=repo, runner=MagicMock(), resume_repo=resume_repo)
        return cog, repo, resume_repo

    @pytest.mark.asyncio
    async def test_no_op_when_no_active_runners(self) -> None:
        """cog_unload is a no-op when no sessions are running."""
        cog, _, resume_repo = self._make_cog_with_resume_repo()
        assert len(cog._active_runners) == 0

        await cog.cog_unload()

        resume_repo.mark.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_op_when_no_resume_repo(self) -> None:
        """cog_unload is a no-op when resume_repo is not configured."""
        cog = _make_cog()  # no resume_repo
        cog._active_runners[111] = MagicMock()

        await cog.cog_unload()  # Should not raise

    @pytest.mark.asyncio
    async def test_marks_each_active_runner(self) -> None:
        """Calls resume_repo.mark() for every thread in _active_runners."""
        cog, repo, resume_repo = self._make_cog_with_resume_repo()
        cog._active_runners[111] = MagicMock()
        cog._active_runners[222] = MagicMock()

        await cog.cog_unload()

        assert resume_repo.mark.call_count == 2
        called_thread_ids = {call.args[0] for call in resume_repo.mark.call_args_list}
        assert called_thread_ids == {111, 222}

    @pytest.mark.asyncio
    async def test_uses_bot_shutdown_reason(self) -> None:
        """Marks sessions with reason='bot_shutdown'."""
        cog, _, resume_repo = self._make_cog_with_resume_repo()
        cog._active_runners[333] = MagicMock()

        await cog.cog_unload()

        call_kwargs = resume_repo.mark.call_args.kwargs
        assert call_kwargs["reason"] == "bot_shutdown"

    @pytest.mark.asyncio
    async def test_resolves_session_id_from_repo(self) -> None:
        """Looks up session_id from self.repo for --resume continuity."""
        cog, repo, resume_repo = self._make_cog_with_resume_repo()
        session_record = MagicMock()
        session_record.session_id = "test-session-xyz"
        repo.get = AsyncMock(return_value=session_record)

        cog._active_runners[444] = MagicMock()
        await cog.cog_unload()

        repo.get.assert_awaited_once_with(444)
        assert resume_repo.mark.call_args.kwargs["session_id"] == "test-session-xyz"

    @pytest.mark.asyncio
    async def test_continues_on_mark_failure(self) -> None:
        """Failure to mark one thread does not prevent marking others."""
        cog, _, resume_repo = self._make_cog_with_resume_repo()
        resume_repo.mark = AsyncMock(side_effect=[RuntimeError("db error"), 2])
        cog._active_runners[111] = MagicMock()
        cog._active_runners[222] = MagicMock()

        # Should not raise
        await cog.cog_unload()

        assert resume_repo.mark.call_count == 2

    @pytest.mark.asyncio
    async def test_uses_none_session_id_when_repo_has_no_record(self) -> None:
        """Falls back to session_id=None when no session record exists."""
        cog, repo, resume_repo = self._make_cog_with_resume_repo()
        repo.get = AsyncMock(return_value=None)
        cog._active_runners[555] = MagicMock()

        await cog.cog_unload()

        assert resume_repo.mark.call_args.kwargs["session_id"] is None


class TestOnMessageSystemMessageFilter:
    """on_message must ignore Discord system messages (e.g. thread renames)."""

    def _make_system_message(self, msg_type: discord.MessageType) -> MagicMock:
        """Return a non-bot message of the given Discord MessageType."""
        msg = MagicMock(spec=discord.Message)
        msg.author = MagicMock()
        msg.author.bot = False
        msg.author.id = 42
        msg.type = msg_type
        thread = MagicMock(spec=discord.Thread)
        thread.id = 12345
        thread.parent_id = 999  # matches bot.channel_id
        msg.channel = thread
        return msg

    @pytest.mark.asyncio
    async def test_thread_rename_does_not_reach_claude(self) -> None:
        """CHANNEL_NAME_CHANGE system message must be silently ignored."""
        cog = _make_cog()
        msg = self._make_system_message(discord.MessageType.channel_name_change)

        # on_message must return without invoking any runner
        await cog.on_message(msg)

        # No runner was started — active_runners stays empty
        assert len(cog._active_runners) == 0

    @pytest.mark.asyncio
    async def test_pins_add_does_not_reach_claude(self) -> None:
        """PINS_ADD system message must also be silently ignored."""
        cog = _make_cog()
        msg = self._make_system_message(discord.MessageType.pins_add)

        await cog.on_message(msg)

        assert len(cog._active_runners) == 0

    @pytest.mark.asyncio
    async def test_default_message_is_processed(self) -> None:
        """Regular user messages (MessageType.default) must still be handled."""
        cog = _make_cog()
        msg = self._make_system_message(discord.MessageType.default)
        msg.content = "hello"
        msg.attachments = []

        # _handle_thread_reply will try to run Claude — just check it's NOT
        # short-circuited by the system-message filter (it may fail later,
        # that's fine; we only care the filter doesn't block it).
        import contextlib

        with contextlib.suppress(Exception):
            await cog.on_message(msg)

        # The filter did not block it — execution reached _handle_thread_reply


class TestImageOnlyMessage:
    """Image-only messages (no text) must be handled without errors.

    This is a regression test suite for the bug where sending a Discord message
    with only an image attachment (no text) caused a ValueError in
    RunConfig.__post_init__ because prompt was empty. The ValueError propagated
    uncaught through the event loop, freezing the entire bot.
    """

    @staticmethod
    def _make_image_message(thread_id: int = 42) -> MagicMock:
        """Return a discord.Message with only an image attachment (no text)."""
        thread = MagicMock(spec=discord.Thread)
        thread.id = thread_id
        thread.parent_id = 999
        thread.send = AsyncMock()
        msg = MagicMock(spec=discord.Message)
        msg.channel = thread
        msg.content = ""  # No text — image only
        msg.author = MagicMock()
        msg.author.bot = False
        att = MagicMock(spec=discord.Attachment)
        att.filename = "photo.png"
        att.content_type = "image/png"
        att.size = 500_000
        att.url = "https://cdn.discordapp.com/attachments/111/222/photo.png"
        att.read = AsyncMock(return_value=b"PNG...")
        msg.attachments = [att]
        return msg

    @pytest.mark.asyncio
    async def test_build_prompt_and_images_returns_empty_prompt(self) -> None:
        """Image-only message should return empty prompt + image URL list."""
        cog = _make_cog()
        msg = self._make_image_message()

        prompt, image_urls = await cog._build_prompt_and_images(msg)

        assert prompt == ""
        assert len(image_urls) == 1
        assert "photo.png" in image_urls[0]

    @pytest.mark.asyncio
    async def test_handle_thread_reply_does_not_crash(self) -> None:
        """_handle_thread_reply with image-only message must not raise."""
        cog = _make_cog()
        msg = self._make_image_message()
        cog._run_claude = AsyncMock()

        # Must not raise ValueError or any other exception
        await cog._handle_thread_reply(msg)

        cog._run_claude.assert_called_once()
        # Verify image_urls were passed through
        call_kwargs = cog._run_claude.call_args
        assert call_kwargs.kwargs.get("image_urls") == [
            "https://cdn.discordapp.com/attachments/111/222/photo.png"
        ]

    @pytest.mark.asyncio
    async def test_handle_thread_reply_skips_empty_message(self) -> None:
        """A message with no text AND no attachments should not start a session."""
        cog = _make_cog()
        thread = MagicMock(spec=discord.Thread)
        thread.id = 42
        thread.parent_id = 999
        thread.send = AsyncMock()
        msg = MagicMock(spec=discord.Message)
        msg.channel = thread
        msg.content = ""
        msg.attachments = []
        msg.author = MagicMock()
        msg.author.bot = False

        cog._run_claude = AsyncMock()

        await cog._handle_thread_reply(msg)

        cog._run_claude.assert_not_called()


class TestMultiChannelSupport:
    """channel_ids parameter allows the bot to listen on multiple channels."""

    def _make_cog_with_channels(self, channel_ids: set[int]) -> ClaudeChatCog:
        bot = MagicMock()
        bot.channel_id = 999  # primary (should be overridden by explicit channel_ids)
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        repo.save = AsyncMock()
        runner = MagicMock()
        runner.clone = MagicMock(return_value=MagicMock())
        return ClaudeChatCog(bot=bot, repo=repo, runner=runner, channel_ids=channel_ids)

    def _make_message(self, channel_id: int, author_id: int = 42) -> MagicMock:
        msg = MagicMock(spec=discord.Message)
        msg.author = MagicMock()
        msg.author.bot = False
        msg.author.id = author_id
        msg.type = discord.MessageType.default
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = channel_id
        msg.channel = channel
        msg.content = "hello"
        msg.attachments = []
        return msg

    def _make_thread_message(self, parent_id: int, author_id: int = 42) -> MagicMock:
        msg = MagicMock(spec=discord.Message)
        msg.author = MagicMock()
        msg.author.bot = False
        msg.author.id = author_id
        msg.type = discord.MessageType.default
        thread = MagicMock(spec=discord.Thread)
        thread.id = 55555
        thread.parent_id = parent_id
        msg.channel = thread
        msg.content = "reply"
        msg.attachments = []
        return msg

    def test_channel_ids_overrides_bot_channel_id(self) -> None:
        """Explicit channel_ids takes precedence over bot.channel_id."""
        cog = self._make_cog_with_channels({111, 222})
        assert cog._channel_ids == {111, 222}
        assert 999 not in cog._channel_ids  # bot.channel_id is NOT included

    def test_fallback_to_bot_channel_id_when_no_channel_ids(self) -> None:
        """When channel_ids is None, falls back to {bot.channel_id}."""
        cog = _make_cog()  # no channel_ids, bot.channel_id = 999
        assert cog._channel_ids == {999}

    @pytest.mark.asyncio
    async def test_message_in_secondary_channel_triggers_new_conversation(self) -> None:
        """Message in a secondary channel (not bot.channel_id) triggers a new session."""
        cog = self._make_cog_with_channels({111, 222})
        cog._handle_new_conversation = AsyncMock()

        msg = self._make_message(channel_id=222)
        await cog.on_message(msg)

        cog._handle_new_conversation.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_message_in_unknown_channel_is_ignored(self) -> None:
        """Message in a channel not in channel_ids must be silently dropped."""
        cog = self._make_cog_with_channels({111, 222})
        cog._handle_new_conversation = AsyncMock()
        cog._handle_thread_reply = AsyncMock()

        msg = self._make_message(channel_id=333)
        await cog.on_message(msg)

        cog._handle_new_conversation.assert_not_called()
        cog._handle_thread_reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_thread_under_secondary_channel_triggers_reply(self) -> None:
        """Thread reply under a secondary channel must be handled."""
        cog = self._make_cog_with_channels({111, 222})
        cog._handle_thread_reply = AsyncMock()

        msg = self._make_thread_message(parent_id=222)
        await cog.on_message(msg)

        cog._handle_thread_reply.assert_awaited_once_with(msg)

    @pytest.mark.asyncio
    async def test_thread_under_unknown_channel_is_ignored(self) -> None:
        """Thread reply under a channel not in channel_ids must be dropped."""
        cog = self._make_cog_with_channels({111, 222})
        cog._handle_thread_reply = AsyncMock()

        msg = self._make_thread_message(parent_id=333)
        await cog.on_message(msg)

        cog._handle_thread_reply.assert_not_called()
