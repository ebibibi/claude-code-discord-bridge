"""Shell exec Cog — オーナー限定のシェルコマンド実行.

Discordから直接VMのシェルコマンドを実行できる。
Claude Codeを経由しないため、settings.jsonの変更など
Claude Codeが自己保護でブロックする操作も実行可能。

セキュリティ:
- DISCORD_OWNER_ID に一致するユーザーのみ実行可能
- 出力は2000文字で切り詰め（Discord制限）
- タイムアウト30秒
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..discord_ui.embeds import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS

if TYPE_CHECKING:
    from ..bot import ClaudeDiscordBot

logger = logging.getLogger(__name__)

# コマンド実行のタイムアウト（秒）
EXEC_TIMEOUT = 30


class ShellExecCog(commands.Cog):
    """オーナー限定: VMでシェルコマンドを直接実行する."""

    def __init__(self, bot: ClaudeDiscordBot) -> None:
        self.bot = bot

    def _is_owner(self, user_id: int) -> bool:
        """リクエスト元がオーナーかどうか確認."""
        return self.bot.owner_id is not None and user_id == self.bot.owner_id

    @app_commands.command(
        name="exec",
        description="VMでシェルコマンドを直接実行（オーナー限定）",
    )
    @app_commands.describe(command="実行するシェルコマンド")
    async def exec_command(
        self,
        interaction: discord.Interaction,
        command: str,
    ) -> None:
        """シェルコマンドを実行して結果を返す."""
        # オーナーチェック
        if not self._is_owner(interaction.user.id):
            embed = discord.Embed(
                title="権限エラー",
                description="このコマンドはサーバーオーナーのみ使用できます。",
                color=COLOR_ERROR,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # 実行開始通知
        embed = discord.Embed(
            title="実行中...",
            description=f"```\n{command}\n```",
            color=COLOR_INFO,
        )
        await interaction.response.send_message(embed=embed)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd="/home/ubuntu",
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=EXEC_TIMEOUT,
            )
        except asyncio.TimeoutError:
            embed = discord.Embed(
                title="タイムアウト",
                description=f"コマンドが{EXEC_TIMEOUT}秒以内に完了しませんでした。",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return
        except Exception as e:
            embed = discord.Embed(
                title="実行エラー",
                description=f"```\n{e}\n```",
                color=COLOR_ERROR,
            )
            await interaction.edit_original_response(embed=embed)
            return

        # 結果を整形
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode

        # Discord メッセージ制限（Embed description: 4096文字）
        max_len = 3800
        parts: list[str] = []
        if out:
            display_out = out[:max_len] + ("..." if len(out) > max_len else "")
            parts.append(f"**stdout:**\n```\n{display_out}\n```")
        if err:
            display_err = err[:1000] + ("..." if len(err) > 1000 else "")
            parts.append(f"**stderr:**\n```\n{display_err}\n```")
        if not parts:
            parts.append("（出力なし）")

        color = COLOR_SUCCESS if exit_code == 0 else COLOR_ERROR
        title = f"完了 (exit {exit_code})" if exit_code == 0 else f"失敗 (exit {exit_code})"

        embed = discord.Embed(
            title=title,
            description="\n".join(parts),
            color=color,
        )
        embed.set_footer(text=f"$ {command}")
        await interaction.edit_original_response(embed=embed)

        logger.info(
            "/exec by %s: %r → exit %s",
            interaction.user.name,
            command,
            exit_code,
        )
