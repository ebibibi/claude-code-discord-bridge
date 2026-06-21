"""/backend and /model slash commands for runtime backend switching.

Persists the selection to ``SettingsRepository`` via ``BackendSettings``
and swaps out ``ClaudeChatCog.runner`` so the next session uses the new
backend immediately. Subsequent sessions inherit the new default.

For now the scope is **global** only (per-thread overrides are persisted
by ``BackendSettings`` and ``ClaudeChatCog`` will honour them when the
factory path lands — keeping the public surface stable across that
follow-up).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from claude_code_core.codex_runner import VALID_CODEX_EFFORTS

from ..backend_settings import ALL_BACKENDS, BackendSettings

if TYPE_CHECKING:
    from ..backend_factory import BackendFactory
    from ..cogs.claude_chat import ClaudeChatCog

logger = logging.getLogger(__name__)


SCOPE_THREAD = "thread"
SCOPE_GLOBAL = "global"

# Valid reasoning-effort levels per backend. Codex and Claude do not share the
# same set (Claude has "max"; Codex has "minimal"/"xhigh"), so /effort validates
# against the level set of whichever backend is currently active.
VALID_EFFORTS: dict[str, frozenset[str]] = {
    "claude": frozenset({"low", "medium", "high", "max"}),
    "codex": VALID_CODEX_EFFORTS,
}


def _model_label(model: str | None) -> str:
    """Human-readable model label; ``None`` means the backend CLI's own default."""
    return f"`{model}`" if model else "_(CLI default)_"


class BackendCommandCog(commands.Cog):
    """/backend and /model slash commands."""

    def __init__(
        self,
        bot: commands.Bot,
        *,
        settings: BackendSettings,
        factory: BackendFactory,
        chat_cog: ClaudeChatCog,
    ) -> None:
        self.bot = bot
        self._settings = settings
        self._factory = factory
        self._chat_cog = chat_cog

    # ── helpers ────────────────────────────────────────────────────

    def _thread_id_or_none(self, interaction: discord.Interaction) -> int | None:
        ch = interaction.channel
        if isinstance(ch, discord.Thread):
            return ch.id
        return None

    def _resolve_scope(
        self, interaction: discord.Interaction, requested: str | None
    ) -> tuple[str, int | None]:
        """Decide whether the command applies to a thread or globally.

        - If ``requested`` is explicit, honour it (require thread context if
          ``thread``).
        - Otherwise: invoked inside a thread → thread; in a channel → global.
        """
        thread_id = self._thread_id_or_none(interaction)
        if requested == SCOPE_GLOBAL:
            return SCOPE_GLOBAL, None
        if requested == SCOPE_THREAD:
            return SCOPE_THREAD, thread_id
        # auto
        if thread_id is not None:
            return SCOPE_THREAD, thread_id
        return SCOPE_GLOBAL, None

    # ── /backend ───────────────────────────────────────────────────

    @app_commands.command(
        name="backend",
        description="Show or switch the AI backend (claude/codex)",
    )
    @app_commands.choices(
        name=[Choice(name=b, value=b) for b in ALL_BACKENDS],
        scope=[
            Choice(name="thread", value=SCOPE_THREAD),
            Choice(name="global", value=SCOPE_GLOBAL),
        ],
    )
    @app_commands.describe(
        name="claude or codex. Omit to show current setting.",
        scope=(
            "thread: only this thread; global: server-wide default. "
            "Default: thread when invoked in a thread, otherwise global."
        ),
    )
    async def backend_command(
        self,
        interaction: discord.Interaction,
        name: str | None = None,
        scope: str | None = None,
    ) -> None:
        thread_id_now = self._thread_id_or_none(interaction)

        # Show current selection if no name provided
        if name is None:
            current_t = (
                await self._settings.current_backend(thread_id_now)
                if thread_id_now is not None
                else None
            )
            current_g = await self._settings.current_backend(None)
            lines: list[str] = [
                f"\U0001f9e0 **Global backend**: `{current_g}`",
            ]
            if thread_id_now is not None and current_t is not None:
                tag = " (thread override)" if current_t != current_g else ""
                lines.append(f"\U0001f9f5 **This thread**: `{current_t}`{tag}")
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            return

        # Validate
        if name not in ALL_BACKENDS:
            await interaction.response.send_message(
                f"Unknown backend `{name}`. Choose: {', '.join(ALL_BACKENDS)}.",
                ephemeral=True,
            )
            return

        resolved_scope, target_thread_id = self._resolve_scope(interaction, scope)
        if resolved_scope == SCOPE_THREAD and target_thread_id is None:
            await interaction.response.send_message(
                "`scope:thread` requires the command to be run inside a thread.",
                ephemeral=True,
            )
            return

        # Persist the new backend. Capture the previous one first so we can
        # detect a real change (and decide whether to wipe the thread's
        # stored session ID, which is not interoperable across backends).
        prev_backend = await self._settings.current_backend(target_thread_id)
        await self._settings.set_backend(name, thread_id=target_thread_id)

        # When the EFFECTIVE backend actually changed, drop any stored
        # session ID so the next message starts a fresh session in the new
        # backend. Codex and Claude session stores are not interoperable
        # (passing a Claude session UUID to `codex exec resume` -- or vice
        # versa -- fails at the CLI level).
        if prev_backend != name and target_thread_id is not None:
            try:
                deleted = await self._chat_cog.repo.delete(target_thread_id)
                if deleted:
                    logger.info(
                        "Cleared stored session for thread %d on backend switch %s -> %s",
                        target_thread_id,
                        prev_backend,
                        name,
                    )
            except Exception:
                logger.exception(
                    "Failed to clear thread %d session on backend change",
                    target_thread_id,
                )

        # If global change, also swap the shared default runner so the next
        # ClaudeChatCog session inherits it (thread overrides will be honoured
        # by ClaudeChatCog at spawn time once it consults BackendSettings).
        if resolved_scope == SCOPE_GLOBAL:
            try:
                model = await self._settings.current_model(name, None)
                new_runner = self._factory.build(backend=name, model=model)
                self._chat_cog.runner = new_runner  # type: ignore[assignment]
                logger.info(
                    "ClaudeChatCog default runner swapped: %s (model=%s)",
                    name,
                    new_runner.model,
                )
            except Exception:
                logger.exception("Failed to swap ClaudeChatCog.runner after /backend change")

        scope_label = (
            f"<#{target_thread_id}>"
            if resolved_scope == SCOPE_THREAD and target_thread_id is not None
            else "**globally**"
        )
        emoji = "\U0001f300" if name == "codex" else "\U0001f916"
        await interaction.response.send_message(
            f"{emoji} Backend set to `{name}` {scope_label}. Next session will use it.",
            ephemeral=False,
        )

    # ── /model ─────────────────────────────────────────────────────

    @app_commands.command(
        name="model",
        description="Show or switch the model for the current backend",
    )
    @app_commands.choices(
        scope=[
            Choice(name="thread", value=SCOPE_THREAD),
            Choice(name="global", value=SCOPE_GLOBAL),
        ],
    )
    @app_commands.describe(
        name="Model id (e.g. sonnet, opus, gpt-5.4, o4-mini). Omit to show current.",
        scope=(
            "thread: only this thread; global: server-wide. "
            "Default: thread when in thread, else global."
        ),
    )
    async def model_command(
        self,
        interaction: discord.Interaction,
        name: str | None = None,
        scope: str | None = None,
    ) -> None:
        thread_id_now = self._thread_id_or_none(interaction)

        # Show current
        if name is None:
            backend_for_thread = (
                await self._settings.current_backend(thread_id_now)
                if thread_id_now is not None
                else await self._settings.current_backend(None)
            )
            current_t = (
                await self._settings.current_model(backend_for_thread, thread_id_now)
                if thread_id_now is not None
                else None
            )
            backend_for_global = await self._settings.current_backend(None)
            current_g = await self._settings.current_model(
                backend_for_global, None
            ) or self._factory.default_model_for(backend_for_global)
            lines: list[str] = [
                f"\U0001f9e0 **Global model**: {_model_label(current_g)} "
                f"(for `{backend_for_global}`)",
            ]
            if thread_id_now is not None:
                resolved_t = current_t or self._factory.default_model_for(backend_for_thread)
                lines.append(
                    f"\U0001f9f5 **This thread**: {_model_label(resolved_t)} "
                    f"(for `{backend_for_thread}`)"
                )
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            return

        resolved_scope, target_thread_id = self._resolve_scope(interaction, scope)
        if resolved_scope == SCOPE_THREAD and target_thread_id is None:
            await interaction.response.send_message(
                "`scope:thread` requires the command to be run inside a thread.",
                ephemeral=True,
            )
            return

        # Determine which backend this model is for: read current backend
        # for the chosen scope.
        backend_for_save = await self._settings.current_backend(
            target_thread_id if resolved_scope == SCOPE_THREAD else None
        )

        await self._settings.set_model(backend_for_save, name, thread_id=target_thread_id)

        # Global change → also update shared runner.model so the next
        # ClaudeChatCog session uses the new model right away.
        if resolved_scope == SCOPE_GLOBAL and self._chat_cog.runner is not None:
            try:
                self._chat_cog.runner.model = name  # type: ignore[assignment]
                logger.info("ClaudeChatCog default runner.model swapped to %s", name)
            except Exception:
                logger.exception("Failed to update ClaudeChatCog.runner.model")

        scope_label = (
            f"<#{target_thread_id}>"
            if resolved_scope == SCOPE_THREAD and target_thread_id is not None
            else "**globally**"
        )
        await interaction.response.send_message(
            f"\U0001f9e0 Model set to `{name}` for `{backend_for_save}` "
            f"{scope_label}. Next session will use it.",
            ephemeral=False,
        )

    # ── /effort ────────────────────────────────────────────────────

    @app_commands.command(
        name="effort",
        description="Show or set the reasoning effort for the current backend",
    )
    @app_commands.choices(
        scope=[
            Choice(name="thread", value=SCOPE_THREAD),
            Choice(name="global", value=SCOPE_GLOBAL),
        ],
    )
    @app_commands.describe(
        level=(
            "Effort level. Claude: low/medium/high/max. "
            "Codex: minimal/low/medium/high/xhigh. Omit to show current."
        ),
        scope=(
            "thread: only this thread; global: server-wide. "
            "Default: thread when in thread, else global."
        ),
    )
    async def effort_command(
        self,
        interaction: discord.Interaction,
        level: str | None = None,
        scope: str | None = None,
    ) -> None:
        thread_id_now = self._thread_id_or_none(interaction)

        # Show current
        if level is None:
            backend_for_global = await self._settings.current_backend(None)
            current_g = await self._settings.current_effort(backend_for_global, None)
            lines: list[str] = [
                f"⚡ **Global effort**: {self._effort_label(current_g)} "
                f"(for `{backend_for_global}`)",
            ]
            if thread_id_now is not None:
                backend_for_thread = await self._settings.current_backend(thread_id_now)
                current_t = await self._settings.current_effort(backend_for_thread, thread_id_now)
                lines.append(
                    f"\U0001f9f5 **This thread**: {self._effort_label(current_t)} "
                    f"(for `{backend_for_thread}`)"
                )
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            return

        resolved_scope, target_thread_id = self._resolve_scope(interaction, scope)
        if resolved_scope == SCOPE_THREAD and target_thread_id is None:
            await interaction.response.send_message(
                "`scope:thread` requires the command to be run inside a thread.",
                ephemeral=True,
            )
            return

        backend_for_save = await self._settings.current_backend(
            target_thread_id if resolved_scope == SCOPE_THREAD else None
        )
        valid = VALID_EFFORTS.get(backend_for_save, frozenset())
        normalized = level.strip().lower()
        if normalized not in valid:
            await interaction.response.send_message(
                f"❌ Unknown effort `{level}` for `{backend_for_save}`. "
                f"Choose: {', '.join(sorted(valid))}.",
                ephemeral=True,
            )
            return

        await self._settings.set_effort(backend_for_save, normalized, thread_id=target_thread_id)

        scope_label = (
            f"<#{target_thread_id}>"
            if resolved_scope == SCOPE_THREAD and target_thread_id is not None
            else "**globally**"
        )
        await interaction.response.send_message(
            f"⚡ Effort set to `{normalized}` for `{backend_for_save}` "
            f"{scope_label}. Next session will use it.",
            ephemeral=False,
        )

    @staticmethod
    def _effort_label(effort: str | None) -> str:
        """Human-readable effort label; ``None`` means the backend CLI's default."""
        return f"`{effort}`" if effort else "_(CLI default)_"
