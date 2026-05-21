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

    from ..database.board_repo import BoardRepository
    from ..database.lounge_repo import LoungeRepository
    from ..database.notification_repo import NotificationRepository
    from ..database.repository import SessionRepository
    from ..database.resume_repo import PendingResumeRepository
    from ..database.task_repo import TaskRepository
    from ..database.usage_repo import UsageRepository

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
        resume_repo: PendingResumeRepository | None = None,
        session_repo: SessionRepository | None = None,
        board_repo: BoardRepository | None = None,
        usage_repo: UsageRepository | None = None,
    ) -> None:
        self.repo = repo
        self.bot = bot
        self.default_channel_id = default_channel_id
        self.host = host
        self.port = port
        self.api_secret = api_secret
        self.task_repo = task_repo
        self.lounge_repo = lounge_repo
        self.resume_repo = resume_repo
        self.session_repo = session_repo
        self.board_repo = board_repo
        self.usage_repo = usage_repo
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
        # Session spawn route
        self.app.router.add_post("/api/spawn", self.spawn)
        # Startup resume routes
        self.app.router.add_post("/api/mark-resume", self.mark_resume)
        # Repository push notification route
        self.app.router.add_post("/api/repo/push-notify", self.push_notify)
        # Channel management routes (requires ChannelManageCog)
        self.app.router.add_post("/api/channels", self.create_channel)
        self.app.router.add_get("/api/channels", self.list_channels)
        self.app.router.add_patch("/api/channels/{id}", self.update_channel)
        self.app.router.add_delete("/api/channels/{id}", self.delete_channel)
        self.app.router.add_post("/api/channels/{id}/webhooks", self.create_channel_webhook)
        self.app.router.add_get("/api/channels/{id}/webhooks", self.list_channel_webhooks)
        self.app.router.add_get("/api/categories", self.list_categories)
        # Discord message reading routes (read-only, for cross-session visibility)
        self.app.router.add_get("/api/channels/{id}/messages", self.get_channel_messages)
        self.app.router.add_get("/api/channels/{id}/threads", self.get_channel_threads)
        # Usage tracking routes (requires usage_repo)
        self.app.router.add_get("/api/usage/summary", self.get_usage_summary)
        self.app.router.add_get("/api/usage/users", self.get_usage_users)
        self.app.router.add_get("/api/usage/daily", self.get_usage_daily)
        self.app.router.add_get("/api/usage/recent", self.get_usage_recent)
        # Project Board routes (requires board_repo)
        self.app.router.add_get("/api/board", self.get_board)
        self.app.router.add_get("/api/board/summary", self.get_board_summary)
        self.app.router.add_post("/api/board", self.create_board_item)
        self.app.router.add_patch("/api/board/{id}", self.update_board_item)
        self.app.router.add_delete("/api/board/{id}", self.delete_board_item)

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
        embed = self._build_embed(
            message=message,
            title=title,
            color=data.get("color"),
            image_url=data.get("image_url"),
            folder_url=data.get("folder_url"),
        )
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

    # ------------------------------------------------------------------
    # Session spawn endpoint (/api/spawn)
    # ------------------------------------------------------------------

    async def spawn(self, request: web.Request) -> web.Response:
        """POST /api/spawn — create a new Discord thread and start Claude Code.

        Unlike posting a message to the channel directly, this endpoint
        bypasses the ``on_message`` bot-author guard and works even when
        called from within another Claude Code session.

        Body (JSON):
            prompt: The instruction to send to Claude (required).
            channel_id: Parent channel ID (optional; defaults to the
                ``default_channel_id`` configured at startup).
            thread_name: Custom thread title (optional; defaults to the
                first 100 characters of *prompt*).

        Returns (201):
            ``{"status": "spawned", "thread_id": "...", "thread_name": "..."}``
        """
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        prompt = (data.get("prompt") or "").strip()
        if not prompt:
            return web.json_response({"error": "prompt is required"}, status=400)

        raw_channel_id = data.get("channel_id") or self.default_channel_id
        if not raw_channel_id:
            return web.json_response({"error": "No channel specified"}, status=400)

        # Resolve ClaudeChatCog lazily from the bot (zero-config; no constructor change).
        from ..cogs.claude_chat import ClaudeChatCog  # avoid circular import at module level

        cog: ClaudeChatCog | None = self.bot.cogs.get("ClaudeChatCog")  # type: ignore[assignment]
        if cog is None:
            return web.json_response(
                {"error": "ClaudeChatCog is not loaded"},
                status=503,
            )

        try:
            channel_id = int(raw_channel_id)
        except (TypeError, ValueError):
            return web.json_response({"error": "channel_id must be an integer"}, status=400)

        import discord as _discord

        raw = self.bot.get_channel(channel_id)
        if raw is None:
            try:
                raw = await self.bot.fetch_channel(channel_id)
            except Exception as exc:
                return web.json_response({"error": str(exc)}, status=500)

        if not isinstance(raw, _discord.TextChannel):
            return web.json_response(
                {"error": "Channel must be a text channel that supports threads"},
                status=400,
            )

        thread_name: str | None = data.get("thread_name") or None

        try:
            thread = await cog.spawn_session(raw, prompt, thread_name=thread_name)
        except Exception as exc:
            logger.error("spawn_session failed: %s", exc, exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)

        logger.info("Spawned new Claude session in thread %s (%s)", thread.id, thread.name)
        return web.json_response(
            {
                "status": "spawned",
                "thread_id": str(thread.id),
                "thread_name": thread.name,
            },
            status=201,
        )

    # ------------------------------------------------------------------
    # Startup resume endpoint (/api/mark-resume)
    # ------------------------------------------------------------------

    def _require_resume_repo(self) -> web.Response | None:
        """Return a 503 response if resume_repo is not configured."""
        if self.resume_repo is None:
            return web.json_response(
                {"error": "PendingResumeRepository not configured (resume_repo is None)"},
                status=503,
            )
        return None

    async def mark_resume(self, request: web.Request) -> web.Response:
        """POST /api/mark-resume — mark a thread for resumption after bot restart.

        Call this **before** running ``systemctl restart discord-bot`` (or any
        equivalent restart command) from within a Claude Code session.  On the
        next bot startup the ``on_ready`` handler will detect the marker,
        re-spawn Claude in this thread, and then delete the marker.

        Body (JSON):
            thread_id: Discord thread ID (required).
            session_id: Claude session ID for ``--resume`` continuity (optional).
            reason: Human-readable reason string (optional, default ``self_restart``).
            resume_prompt: The message to post + send to Claude on resume
                           (optional; a sensible default is used if omitted).

        Returns (201):
            ``{"status": "marked", "id": <row_id>}``
        """
        if err := self._require_resume_repo():
            return err

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        raw_thread_id = data.get("thread_id")
        if not raw_thread_id:
            return web.json_response({"error": "thread_id is required"}, status=400)

        try:
            thread_id = int(raw_thread_id)
        except (TypeError, ValueError):
            return web.json_response({"error": "thread_id must be an integer"}, status=400)

        session_id: str | None = data.get("session_id") or None
        reason: str = str(data.get("reason") or "self_restart")
        resume_prompt: str | None = data.get("resume_prompt") or None

        # Auto-resolve session_id from the sessions table if not provided.
        if session_id is None and self.session_repo is not None:
            try:
                record = await self.session_repo.get(thread_id)
                if record is not None:
                    session_id = record.session_id
                    logger.debug(
                        "mark-resume: auto-resolved session_id=%s for thread %d",
                        session_id,
                        thread_id,
                    )
            except Exception:
                logger.warning(
                    "mark-resume: failed to auto-resolve session_id for thread %d",
                    thread_id,
                    exc_info=True,
                )

        row_id = await self.resume_repo.mark(  # type: ignore[union-attr]
            thread_id,
            session_id=session_id,
            reason=reason,
            resume_prompt=resume_prompt,
        )
        logger.info(
            "Thread %d marked for resume (reason=%s, session_id=%s)",
            thread_id,
            reason,
            session_id,
        )
        return web.json_response({"status": "marked", "id": row_id}, status=201)

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

    # ------------------------------------------------------------------
    # Channel management endpoints (/api/channels)
    # ------------------------------------------------------------------

    def _get_channel_cog(self):
        """Lazily resolve ChannelManageCog from the bot."""
        from ..cogs.channel_manage import ChannelManageCog

        cog: ChannelManageCog | None = self.bot.cogs.get("ChannelManageCog")  # type: ignore[assignment]
        return cog

    async def create_channel(self, request: web.Request) -> web.Response:
        """POST /api/channels — create a text channel with optional webhook.

        Body (JSON):
            name: Channel name (required).
            category: Category name — finds existing or creates new (optional).
            topic: Channel topic/description (optional).
            create_webhook: If true, also create a webhook (default false).
            webhook_name: Custom webhook name (optional).

        Returns (201):
            {"channel_id": "...", "channel_name": "...", "webhook_url": "..."}
        """
        cog = self._get_channel_cog()
        if cog is None:
            return web.json_response(
                {"error": "ChannelManageCog not loaded"},
                status=503,
            )

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        name = (data.get("name") or "").strip()
        if not name:
            return web.json_response({"error": "name is required"}, status=400)

        try:
            result = await cog.create_channel(
                name,
                category=data.get("category"),
                topic=data.get("topic"),
                create_webhook=bool(data.get("create_webhook", False)),
                webhook_name=data.get("webhook_name"),
            )
        except Exception as exc:
            logger.error("Failed to create channel: %s", exc, exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response(result, status=201)

    async def list_channels(self, request: web.Request) -> web.Response:
        """GET /api/channels — list all text channels."""
        cog = self._get_channel_cog()
        if cog is None:
            return web.json_response(
                {"error": "ChannelManageCog not loaded"},
                status=503,
            )

        channels = await cog.list_channels()
        return web.json_response({"channels": channels})

    async def update_channel(self, request: web.Request) -> web.Response:
        """PATCH /api/channels/{id} — update channel name/topic."""
        cog = self._get_channel_cog()
        if cog is None:
            return web.json_response(
                {"error": "ChannelManageCog not loaded"},
                status=503,
            )

        try:
            channel_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid channel ID"}, status=400)

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        try:
            result = await cog.update_channel(
                channel_id,
                name=data.get("name"),
                topic=data.get("topic"),
            )
        except Exception as exc:
            logger.error("Failed to update channel: %s", exc, exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response(result)

    async def delete_channel(self, request: web.Request) -> web.Response:
        """DELETE /api/channels/{id} — delete a channel.

        Query params:
            confirm: Must be "true" to actually delete (safety guard).
        """
        cog = self._get_channel_cog()
        if cog is None:
            return web.json_response(
                {"error": "ChannelManageCog not loaded"},
                status=503,
            )

        try:
            channel_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid channel ID"}, status=400)

        confirm = request.rel_url.query.get("confirm", "").lower()
        if confirm != "true":
            return web.json_response(
                {"error": "Add ?confirm=true to actually delete the channel"},
                status=400,
            )

        try:
            result = await cog.delete_channel(channel_id, reason="Deleted via REST API")
        except Exception as exc:
            logger.error("Failed to delete channel: %s", exc, exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response(result)

    async def create_channel_webhook(self, request: web.Request) -> web.Response:
        """POST /api/channels/{id}/webhooks — create a webhook for a channel.

        Body (JSON):
            webhook_name: Custom webhook name (optional).
        """
        cog = self._get_channel_cog()
        if cog is None:
            return web.json_response(
                {"error": "ChannelManageCog not loaded"},
                status=503,
            )

        try:
            channel_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid channel ID"}, status=400)

        try:
            data = await request.json()
        except json.JSONDecodeError:
            data = {}

        try:
            result = await cog.create_webhook_for_channel(
                channel_id,
                webhook_name=data.get("webhook_name"),
            )
        except Exception as exc:
            logger.error("Failed to create webhook: %s", exc, exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response(result, status=201)

    async def list_channel_webhooks(self, request: web.Request) -> web.Response:
        """GET /api/channels/{id}/webhooks — list webhooks for a channel."""
        cog = self._get_channel_cog()
        if cog is None:
            return web.json_response(
                {"error": "ChannelManageCog not loaded"},
                status=503,
            )

        try:
            channel_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid channel ID"}, status=400)

        try:
            webhooks = await cog.list_webhooks(channel_id)
        except Exception as exc:
            logger.error("Failed to list webhooks: %s", exc, exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response({"webhooks": webhooks})

    async def list_categories(self, request: web.Request) -> web.Response:
        """GET /api/categories — list all channel categories."""
        cog = self._get_channel_cog()
        if cog is None:
            return web.json_response(
                {"error": "ChannelManageCog not loaded"},
                status=503,
            )

        categories = await cog.list_categories()
        return web.json_response({"categories": categories})

    # ------------------------------------------------------------------
    # Discord message reading endpoints
    # ------------------------------------------------------------------

    async def get_channel_messages(self, request: web.Request) -> web.Response:
        """GET /api/channels/{id}/messages — read messages from a channel or thread.

        Query params:
            limit: Number of messages to fetch (default 50, max 200).
            before: Message ID — fetch messages before this ID (for paging).
        """
        import discord as _discord

        try:
            channel_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid channel ID"}, status=400)

        try:
            raw_limit = request.rel_url.query.get("limit", "50")
            limit = max(1, min(200, int(raw_limit)))
        except ValueError:
            return web.json_response({"error": "limit must be an integer"}, status=400)

        before_id = request.rel_url.query.get("before")
        before_obj = None
        if before_id:
            try:
                before_obj = _discord.Object(id=int(before_id))
            except (ValueError, TypeError):
                return web.json_response({"error": "before must be a message ID"}, status=400)

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as exc:
                return web.json_response({"error": str(exc)}, status=404)

        if not hasattr(channel, "history"):
            return web.json_response(
                {"error": "Channel does not support message history"},
                status=400,
            )

        try:
            messages = []
            async for msg in channel.history(limit=limit, before=before_obj):
                author_data = {
                    "id": str(msg.author.id),
                    "username": msg.author.name,
                    "display_name": msg.author.display_name,
                    "bot": msg.author.bot,
                }
                msg_data = {
                    "id": str(msg.id),
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat(),
                    "author": author_data,
                    "attachments": [
                        {"filename": a.filename, "url": a.url}
                        for a in msg.attachments
                    ],
                }
                if msg.thread:
                    msg_data["thread"] = {
                        "id": str(msg.thread.id),
                        "name": msg.thread.name,
                    }
                messages.append(msg_data)
        except _discord.Forbidden:
            return web.json_response({"error": "Bot lacks permission to read this channel"}, status=403)
        except Exception as exc:
            logger.error("Failed to fetch messages: %s", exc, exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response({"messages": messages})

    async def get_channel_threads(self, request: web.Request) -> web.Response:
        """GET /api/channels/{id}/threads — list threads in a channel.

        Returns both active and archived public threads.

        Query params:
            include_archived: "true" to include archived threads (default true).
        """
        import discord as _discord

        try:
            channel_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid channel ID"}, status=400)

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as exc:
                return web.json_response({"error": str(exc)}, status=404)

        if not isinstance(channel, _discord.TextChannel):
            return web.json_response(
                {"error": "Channel must be a text channel"},
                status=400,
            )

        include_archived = request.rel_url.query.get("include_archived", "true").lower() != "false"

        threads_list = []

        try:
            # Active threads from guild cache
            guild = channel.guild
            for thread in guild.threads:
                if thread.parent_id == channel_id:
                    threads_list.append({
                        "id": str(thread.id),
                        "name": thread.name,
                        "archived": thread.archived,
                        "message_count": thread.message_count,
                        "created_at": thread.created_at.isoformat() if thread.created_at else None,
                    })

            # Archived threads
            if include_archived:
                async for thread in channel.archived_threads(limit=50):
                    # Skip if already added from active
                    if not any(t["id"] == str(thread.id) for t in threads_list):
                        threads_list.append({
                            "id": str(thread.id),
                            "name": thread.name,
                            "archived": thread.archived,
                            "message_count": thread.message_count,
                            "created_at": thread.created_at.isoformat() if thread.created_at else None,
                        })
        except _discord.Forbidden:
            return web.json_response({"error": "Bot lacks permission"}, status=403)
        except Exception as exc:
            logger.error("Failed to fetch threads: %s", exc, exc_info=True)
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response({"threads": threads_list})

    # ------------------------------------------------------------------
    # Repository push notification (/api/repo/push-notify)
    # ------------------------------------------------------------------

    async def push_notify(self, request: web.Request) -> web.Response:
        """POST /api/repo/push-notify — send a rich commit notification.

        Called by a git post-push hook to notify Discord about new commits.

        Body (JSON):
            repo_name: Repository name (e.g. "ec-automation-system").
            branch: Branch that was pushed (e.g. "main").
            commits: List of commit objects, each with:
                - sha: Full commit hash.
                - message: Commit message (subject line).
                - author: Author name.
                - files: List of {"status": "M/A/D", "path": "file/path"}.
                - insertions: Number of lines added (optional).
                - deletions: Number of lines deleted (optional).
            github_url: Base GitHub URL (optional).
            channel_id: Target Discord channel (optional; uses default).
        """
        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        repo_name = data.get("repo_name", "unknown")
        branch = data.get("branch", "main")
        commits = data.get("commits", [])
        github_url = data.get("github_url", "")

        if not commits:
            return web.json_response({"error": "No commits provided"}, status=400)

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

        embed = self._build_push_embed(repo_name, branch, commits, github_url)
        await raw_channel.send(embed=embed)  # type: ignore[union-attr]

        return web.json_response({"status": "sent", "commit_count": len(commits)})

    @staticmethod
    def _build_push_embed(
        repo_name: str,
        branch: str,
        commits: list[dict],
        github_url: str,
    ) -> discord.Embed:
        """Build a rich embed for push notification."""
        import discord as _discord

        # Summary
        total_commits = len(commits)
        label = "push" if total_commits == 1 else f"{total_commits} commits"
        title = f"\U0001f514 {repo_name} \u2014 {label} ({branch})"

        lines: list[str] = []
        total_insertions = 0
        total_deletions = 0
        all_files: list[str] = []

        for commit in commits:
            sha_short = commit.get("sha", "")[:7]
            msg = commit.get("message", "(no message)")
            author = commit.get("author", "")
            insertions = commit.get("insertions", 0)
            deletions = commit.get("deletions", 0)
            total_insertions += insertions
            total_deletions += deletions

            commit_line = f"**{msg}**"
            if github_url and sha_short:
                commit_line = f"[`{sha_short}`]({github_url}/commit/{commit.get('sha', '')}) {msg}"
            else:
                commit_line = f"`{sha_short}` {msg}"
            lines.append(f"{commit_line}\nby {author}")

            # Collect files
            for f in commit.get("files", []):
                status = f.get("status", "M")
                path = f.get("path", "")
                icon = {"M": "\u270f\ufe0f", "A": "\U0001f195", "D": "\U0001f5d1\ufe0f"}.get(
                    status, "\U0001f4c4"
                )
                entry = f"{icon} `{path}`"
                if entry not in all_files:
                    all_files.append(entry)

        # Build description
        desc_parts = lines[:5]
        if len(lines) > 5:
            desc_parts.append(f"... +{len(lines) - 5} more commits")

        description = "\n\n".join(desc_parts)

        # Stats line
        stats = f"\n\n**\u5909\u66f4:** {len(all_files)}\u30d5\u30a1\u30a4\u30eb"
        if total_insertions or total_deletions:
            stats += f"\uff08+{total_insertions} / -{total_deletions}\u884c\uff09"

        description += stats

        # File list
        if all_files:
            file_display = "\n".join(all_files[:10])
            if len(all_files) > 10:
                file_display += f"\n... +{len(all_files) - 10}\u30d5\u30a1\u30a4\u30eb"
            description += f"\n\n{file_display}"

        # Truncate to Discord limit
        if len(description) > 4096:
            description = description[:4090] + "\n..."

        embed = _discord.Embed(
            title=title[:256],
            description=description,
            color=0x2ECC71,
            timestamp=datetime.now(),
        )

        if github_url:
            embed.set_footer(text=f"GitHub: {github_url}")

        return embed

    @staticmethod
    def _build_embed(
        message: str,
        title: str | None = None,
        color: int | None = None,
        image_url: str | None = None,
        folder_url: str | None = None,
    ) -> discord.Embed:
        """Build a Discord embed for notification display."""
        import discord

        embed = discord.Embed(
            title=title or "Notification",
            description=message,
            color=color or 0x00BFFF,
            timestamp=datetime.now(),
        )
        if image_url:
            embed.set_image(url=image_url)
        if folder_url:
            embed.add_field(name="出力フォルダ", value=folder_url, inline=False)
        return embed

    # ------------------------------------------------------------------
    # Project Board endpoints (/api/board)
    # ------------------------------------------------------------------

    def _require_board_repo(self) -> web.Response | None:
        """Return a 503 response if board_repo is not configured."""
        if self.board_repo is None:
            return web.json_response(
                {"error": "Project Board not configured (board_repo is None)"},
                status=503,
            )
        return None

    async def get_board(self, request: web.Request) -> web.Response:
        """GET /api/board — list board items with optional filters.

        Query params:
            status: Comma-separated statuses (e.g. "blocked,in_progress").
            category: Filter by category.
            limit: Maximum items (default 100, max 500).
        """
        if err := self._require_board_repo():
            return err

        status = request.rel_url.query.get("status")
        category = request.rel_url.query.get("category")
        try:
            raw_limit = request.rel_url.query.get("limit", "100")
            limit = max(1, min(500, int(raw_limit)))
        except ValueError:
            return web.json_response({"error": "limit must be an integer"}, status=400)

        items = await self.board_repo.list(status=status, category=category, limit=limit)  # type: ignore[union-attr]
        return web.json_response(
            {
                "items": [
                    {
                        "id": item.id,
                        "title": item.title,
                        "category": item.category,
                        "status": item.status,
                        "blocker": item.blocker,
                        "next_action": item.next_action,
                        "priority": item.priority,
                        "wf_id": item.wf_id,
                        "owner": item.owner,
                        "created_at": item.created_at,
                        "updated_at": item.updated_at,
                    }
                    for item in items
                ]
            }
        )

    async def get_board_summary(self, request: web.Request) -> web.Response:
        """GET /api/board/summary — return count of items per status."""
        if err := self._require_board_repo():
            return err

        summary = await self.board_repo.summary()  # type: ignore[union-attr]
        total = sum(summary.values())
        return web.json_response({"summary": summary, "total": total})

    async def create_board_item(self, request: web.Request) -> web.Response:
        """POST /api/board — create a new board item.

        Body (JSON):
            title: Project/task name (required).
            category: Category key (optional, default "other").
            status: Initial status (optional, default "not_started").
            blocker: What's blocking (optional).
            next_action: Next step (optional).
            priority: 1-5 (optional, default 3).
            wf_id: Related n8n workflow ID (optional).
            owner: Who's responsible (optional).
        """
        if err := self._require_board_repo():
            return err

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        title = (data.get("title") or "").strip()
        if not title:
            return web.json_response({"error": "title is required"}, status=400)

        try:
            item = await self.board_repo.create(  # type: ignore[union-attr]
                title=title,
                category=data.get("category", "other"),
                status=data.get("status", "not_started"),
                blocker=data.get("blocker"),
                next_action=data.get("next_action"),
                priority=data.get("priority", 3),
                wf_id=data.get("wf_id"),
                owner=data.get("owner"),
            )
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)

        return web.json_response(
            {
                "status": "created",
                "item": {
                    "id": item.id,
                    "title": item.title,
                    "category": item.category,
                    "status": item.status,
                    "blocker": item.blocker,
                    "next_action": item.next_action,
                    "priority": item.priority,
                    "wf_id": item.wf_id,
                    "owner": item.owner,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                },
            },
            status=201,
        )

    async def update_board_item(self, request: web.Request) -> web.Response:
        """PATCH /api/board/{id} — update a board item.

        Body (JSON): any combination of title, category, status, blocker,
        next_action, priority, wf_id, owner.
        """
        if err := self._require_board_repo():
            return err

        try:
            item_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid item ID"}, status=400)

        try:
            data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        if not data:
            return web.json_response({"error": "No fields to update"}, status=400)

        try:
            item = await self.board_repo.update(item_id, **data)  # type: ignore[union-attr]
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)

        if item is None:
            return web.json_response({"error": "Item not found"}, status=404)

        return web.json_response(
            {
                "status": "updated",
                "item": {
                    "id": item.id,
                    "title": item.title,
                    "category": item.category,
                    "status": item.status,
                    "blocker": item.blocker,
                    "next_action": item.next_action,
                    "priority": item.priority,
                    "wf_id": item.wf_id,
                    "owner": item.owner,
                    "created_at": item.created_at,
                    "updated_at": item.updated_at,
                },
            }
        )

    async def delete_board_item(self, request: web.Request) -> web.Response:
        """DELETE /api/board/{id} — delete a board item."""
        if err := self._require_board_repo():
            return err

        try:
            item_id = int(request.match_info["id"])
        except (ValueError, KeyError):
            return web.json_response({"error": "Invalid item ID"}, status=400)

        deleted = await self.board_repo.delete(item_id)  # type: ignore[union-attr]
        if not deleted:
            return web.json_response({"error": "Item not found"}, status=404)

        return web.json_response({"status": "deleted", "id": item_id})

    # ------------------------------------------------------------------
    # Usage tracking endpoints (/api/usage)
    # ------------------------------------------------------------------

    def _require_usage_repo(self) -> web.Response | None:
        """Return a 503 response if usage_repo is not configured."""
        if self.usage_repo is None:
            return web.json_response(
                {"error": "Usage tracking not configured (usage_repo is None)"},
                status=503,
            )
        return None

    async def get_usage_summary(self, request: web.Request) -> web.Response:
        """GET /api/usage/summary — aggregated usage stats.

        Query params:
            period: "today" (default), "month", or specific date/month.
            date: YYYY-MM-DD for a specific day.
            month: YYYY-MM for a specific month.
        """
        if err := self._require_usage_repo():
            return err

        period = request.rel_url.query.get("period", "today")
        date = request.rel_url.query.get("date")
        month = request.rel_url.query.get("month")

        if date:
            summary = await self.usage_repo.get_daily_summary(date)  # type: ignore[union-attr]
        elif month or period == "month":
            summary = await self.usage_repo.get_monthly_summary(month)  # type: ignore[union-attr]
        else:
            summary = await self.usage_repo.get_daily_summary()  # type: ignore[union-attr]

        return web.json_response({
            "summary": {
                "total_sessions": summary.total_sessions,
                "total_cost_usd": round(summary.total_cost_usd, 4),
                "total_input_tokens": summary.total_input_tokens,
                "total_output_tokens": summary.total_output_tokens,
                "total_duration_ms": summary.total_duration_ms,
            }
        })

    async def get_usage_users(self, request: web.Request) -> web.Response:
        """GET /api/usage/users — per-user usage breakdown.

        Query params:
            date: YYYY-MM-DD for a specific day (default: today).
            month: YYYY-MM for a specific month.
        """
        if err := self._require_usage_repo():
            return err

        date = request.rel_url.query.get("date")
        month = request.rel_url.query.get("month")

        users = await self.usage_repo.get_user_summaries(date=date, year_month=month)  # type: ignore[union-attr]

        return web.json_response({
            "users": [
                {
                    "discord_user_id": u.discord_user_id,
                    "discord_username": u.discord_username,
                    "total_sessions": u.total_sessions,
                    "total_cost_usd": round(u.total_cost_usd, 4),
                    "total_input_tokens": u.total_input_tokens,
                    "total_output_tokens": u.total_output_tokens,
                    "total_duration_ms": u.total_duration_ms,
                }
                for u in users
            ]
        })

    async def get_usage_daily(self, request: web.Request) -> web.Response:
        """GET /api/usage/daily — daily cost breakdown for a month.

        Query params:
            month: YYYY-MM (default: current month).
        """
        if err := self._require_usage_repo():
            return err

        month = request.rel_url.query.get("month")
        breakdown = await self.usage_repo.get_daily_breakdown(year_month=month)  # type: ignore[union-attr]

        return web.json_response({"days": breakdown})

    async def get_usage_recent(self, request: web.Request) -> web.Response:
        """GET /api/usage/recent — most recent usage records.

        Query params:
            limit: Number of records (default 20, max 100).
        """
        if err := self._require_usage_repo():
            return err

        try:
            raw_limit = request.rel_url.query.get("limit", "20")
            limit = max(1, min(100, int(raw_limit)))
        except ValueError:
            return web.json_response({"error": "limit must be an integer"}, status=400)

        records = await self.usage_repo.get_recent(limit=limit)  # type: ignore[union-attr]

        return web.json_response({
            "records": [
                {
                    "id": r.id,
                    "thread_id": r.thread_id,
                    "session_id": r.session_id,
                    "discord_user_id": r.discord_user_id,
                    "discord_username": r.discord_username,
                    "bot_name": r.bot_name,
                    "model": r.model,
                    "cost_usd": round(r.cost_usd, 4) if r.cost_usd else None,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "duration_ms": r.duration_ms,
                    "prompt_summary": r.prompt_summary,
                    "created_at": r.created_at,
                }
                for r in records
            ]
        })
