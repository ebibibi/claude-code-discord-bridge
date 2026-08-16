"""`/ask` — send one anonymized question to a strong external model.

The companion to the local-model backend: a thread does its work locally, and
when it needs research, a second opinion or a plan, the human sends exactly one
question out. The external model gets no tools, no files and no project
context, so what left the machine is exactly the line recorded in the audit log.

The command is only registered when a rules file exists. Without one there is
nothing to anonymize, and a `/ask` that quietly forwards real names would be
worse than no command at all.
"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from claude_code_core.escalation import ConsultChannel, Escalation, IsolationError
from claude_code_core.privacy import get_gateway

logger = logging.getLogger(__name__)

__all__ = ["AskCommandCog"]

_MAX_ANSWER_CHARS = 1800


class AskCommandCog(commands.Cog):
    """Slash command for explicit, anonymized escalation to an external model."""

    def __init__(self, bot: commands.Bot, *, model: str = "sonnet") -> None:
        self.bot = bot
        self.model = model

    @app_commands.command(
        name="ask",
        description="Ask a strong external model one anonymized, self-contained question",
    )
    @app_commands.describe(
        question="Self-contained question. Identifying terms are replaced before it is sent.",
        show_sent="Also show the exact text that left this machine (default: yes)",
    )
    async def ask(
        self,
        interaction: discord.Interaction,
        question: str,
        show_sent: bool = True,
    ) -> None:
        gateway = get_gateway()
        if gateway is None:
            await interaction.response.send_message(
                "`/ask` needs an anonymization rules file. Without one nothing would be "
                "replaced, so the question is not sent. See docs/anonymization.md.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        escalation = Escalation(gateway=gateway, channel=ConsultChannel(model=self.model))

        try:
            outcome = await escalation.consult(
                question,
                thread_id=getattr(interaction.channel, "id", None),
                user_id=interaction.user.id,
            )
        except IsolationError as exc:
            logger.warning("Escalation refused: %s", exc)
            await interaction.followup.send(f"🛑 {exc}")
            return
        except Exception:
            logger.exception("Escalation failed")
            await interaction.followup.send(
                "🛑 The external model could not be reached. Nothing was retried automatically."
            )
            return

        if outcome.blocked:
            await interaction.followup.send(f"🛑 {outcome.reason}")
            return

        parts: list[str] = []
        if outcome.warning:
            parts.append(f"⚠️ {outcome.warning}")
        if show_sent:
            parts.append(
                f"📤 **Sent** ({outcome.substitutions} replaced):\n> "
                + outcome.question_sent.replace("\n", "\n> ")
            )
        answer = outcome.answer
        if len(answer) > _MAX_ANSWER_CHARS:
            answer = answer[:_MAX_ANSWER_CHARS] + "\n…(truncated)"
        parts.append(answer)
        await interaction.followup.send("\n\n".join(parts))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AskCommandCog(bot))
