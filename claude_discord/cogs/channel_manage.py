"""Channel management Cog.

Provides slash commands and helpers for creating/managing Discord channels,
categories, and webhooks programmatically.

This is the foundation for n8n WFs, GAS scripts, and other automations
to self-provision their own notification channels without manual setup.

Required bot permissions:
- Manage Channels
- Manage Webhooks
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from ..discord_ui.embeds import COLOR_ERROR, COLOR_INFO, COLOR_SUCCESS

if TYPE_CHECKING:
    from ..bot import ClaudeDiscordBot

logger = logging.getLogger(__name__)


class ChannelManageCog(commands.Cog):
    """Cog for Discord channel and webhook management."""

    def __init__(self, bot: ClaudeDiscordBot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_guild(self) -> discord.Guild | None:
        """Resolve the guild from the bot's configured channel."""
        channel = self.bot.get_channel(self.bot.channel_id)
        if channel is not None and hasattr(channel, "guild"):
            return channel.guild  # type: ignore[union-attr]
        return None

    async def _find_or_create_category(
        self,
        guild: discord.Guild,
        category_name: str | None,
    ) -> discord.CategoryChannel | None:
        """Find an existing category by name or create a new one."""
        if not category_name:
            return None

        # Search existing categories (case-insensitive)
        for cat in guild.categories:
            if cat.name.lower() == category_name.lower():
                return cat

        # Create new category
        try:
            category = await guild.create_category(category_name)
            logger.info("Created category: %s (ID: %d)", category.name, category.id)
            return category
        except discord.Forbidden:
            logger.error("Missing permission to create category: %s", category_name)
            return None

    # ------------------------------------------------------------------
    # Public API (called by api_server.py)
    # ------------------------------------------------------------------

    async def create_channel(
        self,
        name: str,
        *,
        category: str | None = None,
        topic: str | None = None,
        create_webhook: bool = False,
        webhook_name: str | None = None,
    ) -> dict:
        """Create a text channel with optional category and webhook.

        Returns a dict with channel_id, channel_name, and optionally webhook_url.
        Raises ValueError or discord.Forbidden on failure.
        """
        guild = self._get_guild()
        if guild is None:
            raise ValueError("Could not resolve guild from bot's configured channel")

        # Resolve or create category
        cat = await self._find_or_create_category(guild, category)

        # Create the text channel
        channel = await guild.create_text_channel(
            name=name,
            category=cat,
            topic=topic,
        )
        logger.info(
            "Created channel: #%s (ID: %d, category: %s)",
            channel.name,
            channel.id,
            cat.name if cat else "none",
        )

        result: dict = {
            "channel_id": str(channel.id),
            "channel_name": channel.name,
        }
        if cat:
            result["category_name"] = cat.name

        # Create webhook if requested
        if create_webhook:
            wh_name = webhook_name or f"{channel.name}-webhook"
            webhook = await channel.create_webhook(name=wh_name)
            result["webhook_url"] = webhook.url
            result["webhook_id"] = str(webhook.id)
            logger.info("Created webhook: %s for #%s", wh_name, channel.name)

        return result

    async def list_channels(self) -> list[dict]:
        """List all text channels in the guild."""
        guild = self._get_guild()
        if guild is None:
            return []

        channels = []
        for ch in guild.text_channels:
            entry: dict = {
                "channel_id": str(ch.id),
                "channel_name": ch.name,
                "topic": ch.topic or "",
            }
            if ch.category:
                entry["category"] = ch.category.name
            channels.append(entry)
        return channels

    async def update_channel(
        self,
        channel_id: int,
        *,
        name: str | None = None,
        topic: str | None = None,
    ) -> dict:
        """Update a channel's name and/or topic."""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)

        if not isinstance(channel, discord.TextChannel):
            raise ValueError(f"Channel {channel_id} is not a text channel")

        kwargs: dict = {}
        if name is not None:
            kwargs["name"] = name
        if topic is not None:
            kwargs["topic"] = topic

        if kwargs:
            await channel.edit(**kwargs)
            logger.info("Updated channel #%s (ID: %d): %s", channel.name, channel.id, kwargs)

        return {
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "topic": channel.topic or "",
        }

    async def delete_channel(self, channel_id: int, *, reason: str | None = None) -> dict:
        """Delete a channel by ID."""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)

        if not isinstance(channel, discord.TextChannel):
            raise ValueError(f"Channel {channel_id} is not a text channel")

        channel_name = channel.name
        await channel.delete(reason=reason)
        logger.info("Deleted channel #%s (ID: %d)", channel_name, channel_id)

        return {"channel_id": str(channel_id), "channel_name": channel_name, "deleted": True}

    async def create_webhook_for_channel(
        self,
        channel_id: int,
        webhook_name: str | None = None,
    ) -> dict:
        """Create a webhook for an existing channel."""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)

        if not isinstance(channel, discord.TextChannel):
            raise ValueError(f"Channel {channel_id} is not a text channel")

        wh_name = webhook_name or f"{channel.name}-webhook"
        webhook = await channel.create_webhook(name=wh_name)
        logger.info("Created webhook: %s for #%s", wh_name, channel.name)

        return {
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "webhook_id": str(webhook.id),
            "webhook_url": webhook.url,
        }

    async def list_webhooks(self, channel_id: int) -> list[dict]:
        """List all webhooks for a channel."""
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            channel = await self.bot.fetch_channel(channel_id)

        if not isinstance(channel, discord.TextChannel):
            raise ValueError(f"Channel {channel_id} is not a text channel")

        webhooks = await channel.webhooks()
        return [
            {
                "webhook_id": str(wh.id),
                "webhook_name": wh.name or "",
                "webhook_url": wh.url,
            }
            for wh in webhooks
        ]

    async def list_categories(self) -> list[dict]:
        """List all categories in the guild."""
        guild = self._get_guild()
        if guild is None:
            return []

        return [
            {
                "category_id": str(cat.id),
                "category_name": cat.name,
                "channel_count": len(cat.text_channels),
            }
            for cat in guild.categories
        ]

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    @app_commands.command(name="channel-create", description="テキストチャンネルを作成（Webhook自動発行オプション付き）")
    @app_commands.describe(
        name="チャンネル名",
        category="カテゴリ名（既存or新規作成）",
        topic="チャンネルの説明",
        create_webhook="Webhookも同時に作成するか",
    )
    async def channel_create(
        self,
        interaction: discord.Interaction,
        name: str,
        category: str | None = None,
        topic: str | None = None,
        create_webhook: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.create_channel(
                name,
                category=category,
                topic=topic,
                create_webhook=create_webhook,
            )
            embed = discord.Embed(
                title="チャンネル作成完了",
                color=COLOR_SUCCESS,
            )
            embed.add_field(name="チャンネル", value=f"<#{result['channel_id']}>", inline=True)
            if result.get("category_name"):
                embed.add_field(name="カテゴリ", value=result["category_name"], inline=True)
            if result.get("webhook_url"):
                # Webhook URLはephemeralで表示（セキュリティ）
                embed.add_field(name="Webhook URL", value=f"```\n{result['webhook_url']}\n```", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            embed = discord.Embed(
                title="権限エラー",
                description="Botに「チャンネルの管理」権限がありません。\nDiscord Developer Portalで権限を追加してください。",
                color=COLOR_ERROR,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(title="エラー", description=str(e), color=COLOR_ERROR)
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="channel-list", description="テキストチャンネル一覧を表示")
    async def channel_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        channels = await self.list_channels()
        if not channels:
            await interaction.followup.send("チャンネルが見つかりません。", ephemeral=True)
            return

        # Group by category
        grouped: dict[str, list[dict]] = {}
        for ch in channels:
            cat = ch.get("category", "（カテゴリなし）")
            grouped.setdefault(cat, []).append(ch)

        lines: list[str] = []
        for cat_name, chs in grouped.items():
            lines.append(f"**{cat_name}**")
            for ch in chs:
                topic_preview = f" — {ch['topic'][:40]}" if ch.get("topic") else ""
                lines.append(f"  <#{ch['channel_id']}>{topic_preview}")
            lines.append("")

        embed = discord.Embed(
            title="チャンネル一覧",
            description="\n".join(lines)[:4096],
            color=COLOR_INFO,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="channel-webhook", description="既存チャンネルにWebhookを作成")
    @app_commands.describe(
        channel="Webhookを作成するチャンネル",
        webhook_name="Webhook名（省略時はチャンネル名-webhook）",
    )
    async def channel_webhook(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        webhook_name: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.create_webhook_for_channel(
                channel.id,
                webhook_name=webhook_name,
            )
            embed = discord.Embed(
                title="Webhook作成完了",
                color=COLOR_SUCCESS,
            )
            embed.add_field(name="チャンネル", value=f"<#{result['channel_id']}>", inline=True)
            embed.add_field(name="Webhook名", value=result.get("webhook_id", ""), inline=True)
            embed.add_field(name="Webhook URL", value=f"```\n{result['webhook_url']}\n```", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.Forbidden:
            embed = discord.Embed(
                title="権限エラー",
                description="Botに「Webhookの管理」権限がありません。",
                color=COLOR_ERROR,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(title="エラー", description=str(e), color=COLOR_ERROR)
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="webhook-list", description="チャンネルのWebhook一覧を表示")
    @app_commands.describe(channel="Webhookを確認するチャンネル")
    async def webhook_list(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            webhooks = await self.list_webhooks(channel.id)
            if not webhooks:
                await interaction.followup.send(
                    f"<#{channel.id}> にWebhookはありません。",
                    ephemeral=True,
                )
                return

            lines = []
            for wh in webhooks:
                lines.append(f"**{wh['webhook_name']}** (`{wh['webhook_id']}`)")
                lines.append(f"```\n{wh['webhook_url']}\n```")

            embed = discord.Embed(
                title=f"#{channel.name} のWebhook一覧",
                description="\n".join(lines)[:4096],
                color=COLOR_INFO,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(title="エラー", description=str(e), color=COLOR_ERROR)
            await interaction.followup.send(embed=embed, ephemeral=True)
