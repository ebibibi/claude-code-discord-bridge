"""REST API server for Discord bot push notifications.

Optional extension — requires aiohttp. Install with:
    pip install claude-code-discord-bridge[api]

Provides endpoints for sending immediate and scheduled notifications
to Discord channels via the bot.

Security:
- Binds to 127.0.0.1 by default (localhost only)
- Optional Bearer token authentication via api_secret
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    import discord
    from discord.ext.commands import Bot

    from ..database.lounge_repo import LoungeRepository
    from ..database.notification_repo import NotificationRepository
    from ..database.task_repo import TaskRepository

logger = logging.getLogger(__name__)


class ApiServer:
    """Embedded REST API server for Discord bot notifications.

    Usage::

        from claude_discord.database.notification_repo import NotificationRepository
        from claude_discord.ext.api_server import ApiServer

        repo = NotificationRepository("data/notifications.db")
        await repo.init_db()
        api = ApiServer(repo=repo, bot=bot, default_channel_id=12345)
        await api.start()
        # ... bot runs ...
        await api.stop()
    """

    def __init__(
        self,
        repo: NotificationRepository,
        bot: Bot,
        default_channel_id: int | None = None,
        host: str = "127.0.0.1",
        port: int = 8080,
        api_secret: str | None = None,
        task_repo: TaskRepository | None = None,
        lounge_repo: LoungeRepository | None = None,
        lounge_channel_id: int | None = None,
    ) -> None:
        self.repo = repo
        self.bot = bot
        self.default_channel_id = default_channel_id
        self.host = host
        self.port = port
        self.api_secret = api_secret
        self.task_repo = task_repo
        self.lounge_repo = lounge_repo
        # Fall back to COORDINATION_CHANNEL_ID so lounge shares the same channel
        if lounge_channel_id is None:
            ch_str = os.getenv("COORDINATION_CHANNEL_ID", "")
            lounge_channel_id = int(ch_str) if ch_str.isdigit() else None
        self.lounge_channel_id = lounge_channel_id

        self.app = web.Application()
        if self.api_secret:
            self.app.middlewares.append(self._auth_middleware)
        self._setup_routes()
        self._runner: web.AppRunner | None = None

    def _setup_routes(self) -> None:
        self.app.router.add_get("/api/health", self.health)
        self.app.router.add_post("/api/notify", self.notify)
        self.app.router.add_post("/api/schedule", self.schedule)
        self.app.router.add_get("/api/scheduled", self.list_scheduled)
        self.app.router.add_delete("/api/scheduled/{id}", self.cancel_scheduled)
        # Scheduled task routes (requires task_repo)
        self.app.router.add_post("/api/tasks", self.create_task)
        self.app.router.add_get("/api/tasks", self.list_tasks)
        self.app.router.add_delete("/api/tasks/{id}", self.delete_task)
        self.app.router.add_patch("/api/tasks/{id}", self.patch_task)
        # AI Lounge routes (requires lounge_repo)
        self.app.router.add_get("/api/lounge", self.get_lounge)
        self.app.router.add_post("/api/lounge", self.post_lounge)

    @web.middleware
    async def _auth_middleware(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        """Bearer token authentication middleware."""
        if request.path == "/api/health":
            return await handler(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return web.json_response({"error": "Missing Authorization header"}, status=401)

        token = auth_header[7:]
        if token != self.api_secret:
            return web.json_response({"error": "Invalid token"}, status=401)

        return await handler(request)

    async def start(self) -> None:
        """Start the API server."""
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("REST API started: http://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop the API server."""
        if self._runner:
            await self._runner.cleanup()

    async def health(self, request: web.Request) -> web.Response:
        """GET /api/health — health check."""
        return web.json_response(
            {
                "status": "ok",
                "timestamp": datetime.now().isoformat(),
            }
        )

    async def notify(self, request: web.Request) -> web.Response:
        """POST /api/notify — send an immediate notification."""
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        message = data.get("message")
        if not message:
            return web.json_response({"error": "message is required"}, status=400)

        channel_id = data.get("channel_id") or self.default_channel_id
        if not channel_id:
            return web.json_response({"error": "No channel specified"}, status=400)

        raw_channel = self.bot.get_channel(channel_id)
        if not raw_channel:
            try:
                raw_channel = await self.bot.fetch_channel(channel_id)
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)

        if not hasattr(raw_channel, "send"):
            return web.json_response({"error": "Channel is not messageable"}, status=400)

        title = data.get("title")
        embed = self._build_embed(message=message, title=title, color=data.get("color"))
        await raw_channel.send(embed=embed)  # type: ignore[union-attr]

        return web.json_response({"status": "sent"})

    async def schedule(self, request: web.Request) -> web.Response:
        """POST /api/schedule — schedule a notification for later."""
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        message = data.get("message")
        scheduled_at = data.get("scheduled_at")

        if not message:
            return web.json_response({"error": "message is required"}, status=400)
        if not scheduled_at:
            return web.json_response({"error": "scheduled_at is required"}, status=400)

        try:
            dt = datetime.fromisoformat(scheduled_at)
            scheduled_str = dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return web.json_response(
                {"error": "scheduled_at must be ISO 8601 format"},
                status=400,
            )

        notification_id = await self.repo.create(
            message=message,
            scheduled_at=scheduled_str,
            title=data.get("title"),
            color=data.get("color", 0x00BFFF),
            source="api",
            channel_id=data.get("channel_id"),
        )

        return web.json_response({"status": "scheduled", "id": notification_id})

    async def list_scheduled(self, request: web.Request) -> web.Response:
        """GET /api/scheduled — list pending notifications."""
        pending = await self.repo.get_pending()
        return web.json_response({"notifications": pending})

    async def cancel_scheduled(self, request: web.Request) -> web.Response:
        """DELETE /api/scheduled/{id} — cancel a pending notification."""
        try:
            notification_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid ID"}, status=400)

        success = await self.repo.cancel(notification_id)
        if success:
            return web.json_response({"status": "cancelled"})
        return web.json_response(
            {"error": "Not found or already processed"},
            status=404,
        )

    # ------------------------------------------------------------------
    # Scheduled task endpoints (/api/tasks)
    # ------------------------------------------------------------------

    def _require_task_repo(self) -> web.Response | None:
        """Return a 503 response if task_repo is not configured."""
        if self.task_repo is None:
            return web.json_response(
                {"error": "SchedulerCog not configured (task_repo is None)"},
                status=503,
            )
        return None

    async def create_task(self, request: web.Request) -> web.Response:
        """POST /api/tasks — register a scheduled Claude Code task.

        Body (JSON):
            name: Unique task identifier.
            prompt: Claude Code prompt to run on schedule.
            interval_seconds: How often to run (seconds).
            channel_id: Discord channel ID for thread creation.
            working_dir: (optional) Working directory for Claude.
            run_immediately: (optional, default true) Fire on next loop tick.
        """
        if err := self._require_task_repo():
            return err
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        for field in ("name", "prompt", "interval_seconds", "channel_id"):
            if not data.get(field):
                return web.json_response({"error": f"{field} is required"}, status=400)

        try:
            task_id = await self.task_repo.create(  # type: ignore[union-attr]
                name=str(data["name"]),
                prompt=str(data["prompt"]),
                interval_seconds=int(data["interval_seconds"]),
                channel_id=int(data["channel_id"]),
                working_dir=data.get("working_dir"),
                run_immediately=bool(data.get("run_immediately", True)),
            )
        except Exception as exc:
            # Most likely a UNIQUE constraint violation on name
            logger.warning("Failed to create task: %s", exc)
            return web.json_response({"error": "Task name already exists"}, status=409)

        logger.info("Task registered via API: id=%d, name=%s", task_id, data["name"])
        return web.json_response({"status": "created", "id": task_id}, status=201)

    async def list_tasks(self, request: web.Request) -> web.Response:
        """GET /api/tasks — list all registered tasks."""
        if err := self._require_task_repo():
            return err
        tasks = await self.task_repo.get_all()  # type: ignore[union-attr]
        return web.json_response({"tasks": tasks})

    async def delete_task(self, request: web.Request) -> web.Response:
        """DELETE /api/tasks/{id} — remove a scheduled task."""
        if err := self._require_task_repo():
            return err
        try:
            task_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid ID"}, status=400)

        deleted = await self.task_repo.delete(task_id)  # type: ignore[union-attr]
        if deleted:
            return web.json_response({"status": "deleted"})
        return web.json_response({"error": "Task not found"}, status=404)

    async def patch_task(self, request: web.Request) -> web.Response:
        """PATCH /api/tasks/{id} — update a task (enable/disable, prompt, interval)."""
        if err := self._require_task_repo():
            return err
        try:
            task_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid ID"}, status=400)

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        updated = False
        if "enabled" in data:
            result = await self.task_repo.set_enabled(task_id, enabled=bool(data["enabled"]))  # type: ignore[union-attr]
            updated = updated or result

        patch_kwargs: dict[str, object] = {}
        if "prompt" in data:
            patch_kwargs["prompt"] = str(data["prompt"])
        if "interval_seconds" in data:
            patch_kwargs["interval_seconds"] = int(data["interval_seconds"])
        if "working_dir" in data:
            patch_kwargs["working_dir"] = str(data["working_dir"])

        if patch_kwargs:
            result = await self.task_repo.update(task_id, **patch_kwargs)  # type: ignore[union-attr]
            updated = updated or result

        if updated:
            return web.json_response({"status": "updated"})
        return web.json_response({"error": "Task not found"}, status=404)

    # ------------------------------------------------------------------
    # AI Lounge endpoints (/api/lounge)
    # ------------------------------------------------------------------

    def _require_lounge_repo(self) -> web.Response | None:
        """Return a 503 response if lounge_repo is not configured."""
        if self.lounge_repo is None:
            return web.json_response(
                {"error": "AI Lounge not configured (lounge_repo is None)"},
                status=503,
            )
        return None

    async def get_lounge(self, request: web.Request) -> web.Response:
        """GET /api/lounge — list recent AI Lounge messages.

        Query params:
            limit: Maximum number of messages to return (default 10, max 50).
        """
        if err := self._require_lounge_repo():
            return err

        try:
            raw_limit = request.rel_url.query.get("limit", "10")
            limit = max(1, min(50, int(raw_limit)))
        except ValueError:
            return web.json_response({"error": "limit must be an integer"}, status=400)

        messages = await self.lounge_repo.get_recent(limit=limit)  # type: ignore[union-attr]
        return web.json_response(
            {
                "messages": [
                    {
                        "id": m.id,
                        "label": m.label,
                        "message": m.message,
                        "posted_at": m.posted_at,
                    }
                    for m in messages
                ]
            }
        )

    async def post_lounge(self, request: web.Request) -> web.Response:
        """POST /api/lounge — post a message to the AI Lounge.

        Body (JSON):
            message: The lounge message text (required).
            label: The sender's label/nickname (optional, default "AI").

        The message is stored in SQLite and forwarded to the configured
        lounge Discord channel (if lounge_channel_id is set).
        """
        if err := self._require_lounge_repo():
            return err

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        message = data.get("message", "").strip()
        if not message:
            return web.json_response({"error": "message is required"}, status=400)

        label = str(data.get("label", "AI")).strip() or "AI"

        stored = await self.lounge_repo.post(message=message, label=label)  # type: ignore[union-attr]

        # Forward to Discord lounge channel if configured
        if self.lounge_channel_id:
            await self._send_lounge_to_discord(stored.label, stored.message, stored.posted_at)

        return web.json_response(
            {
                "status": "posted",
                "id": stored.id,
                "label": stored.label,
                "message": stored.message,
                "posted_at": stored.posted_at,
            },
            status=201,
        )

    async def _send_lounge_to_discord(self, label: str, message: str, posted_at: str) -> None:
        """Send a lounge message to the configured Discord lounge channel."""
        try:
            channel = self.bot.get_channel(self.lounge_channel_id)  # type: ignore[arg-type]
            if channel is None:
                channel = await self.bot.fetch_channel(self.lounge_channel_id)  # type: ignore[arg-type]
            if hasattr(channel, "send"):
                timestamp = posted_at[11:16] if len(posted_at) >= 16 else posted_at
                await channel.send(f"**[{label}]** {message} *({timestamp})*")  # type: ignore[union-attr]
        except Exception:
            logger.warning("Failed to forward lounge message to Discord", exc_info=True)

    @staticmethod
    def _build_embed(
        message: str,
        title: str | None = None,
        color: int | None = None,
    ) -> discord.Embed:
        """Build a Discord embed for notification display."""
        import discord

        return discord.Embed(
            title=title or "Notification",
            description=message,
            color=color or 0x00BFFF,
            timestamp=datetime.now(),
        )
