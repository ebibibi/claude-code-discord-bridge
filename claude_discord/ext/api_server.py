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

import contextlib
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    import discord
    from discord.ext.commands import Bot

    from ..database.lounge_repo import LoungeRepository
    from ..database.notification_repo import NotificationRepository
    from ..database.repository import SessionRepository
    from ..database.resume_repo import PendingResumeRepository
    from ..database.task_repo import TaskRepository

logger = logging.getLogger(__name__)


def _sanitize_log(value: object) -> str:
    """Sanitize user-provided values before writing to logs.

    Strips newline and carriage-return characters to prevent log injection
    attacks where an attacker embeds fake log entries in a single field.
    """
    return re.sub(r"[\r\n]", " ", str(value))


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
        site = web.TCPSite(self._runner, self.host, self.port, reuse_address=True)
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

        # Build poll if specified
        poll_data = data.get("poll")
        poll_obj = None
        if poll_data:
            poll_result = self._build_poll(poll_data)
            if isinstance(poll_result, web.Response):
                return poll_result
            poll_obj = poll_result

        thread_name = data.get("thread_name")
        fmt = data.get("format", "text" if thread_name else "embed")

        # Determine target: create a new thread or send directly to channel
        if thread_name:
            if not hasattr(raw_channel, "create_thread"):
                return web.json_response({"error": "Channel does not support threads"}, status=400)
            thread_result = await raw_channel.create_thread(name=thread_name)  # type: ignore[union-attr]
            # create_thread may return Thread or ThreadWithMessage depending on discord.py version
            thread = thread_result.thread if hasattr(thread_result, "thread") else thread_result  # type: ignore[union-attr]
            target = thread
        else:
            target = raw_channel
            thread = None

        if poll_obj:
            await target.send(content=message, poll=poll_obj)  # type: ignore[union-attr]
        elif fmt == "text":
            await target.send(message)  # type: ignore[union-attr]
        else:
            title = data.get("title")
            embed = self._build_embed(message=message, title=title, color=data.get("color"))
            await target.send(embed=embed)  # type: ignore[union-attr]

        result: dict[str, str] = {"status": "sent"}
        if thread is not None:
            result["thread_id"] = str(thread.id)  # type: ignore[union-attr]
            result["thread_name"] = thread.name  # type: ignore[union-attr]
        return web.json_response(result)

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

    @staticmethod
    def _parse_anchor_time(raw: str | None) -> tuple[int | None, int | None]:
        """Parse ``"HH:MM"`` into (hour, minute).  Returns (None, None) if absent."""
        if not raw:
            return None, None
        parts = raw.split(":")
        if len(parts) != 2:  # noqa: PLR2004
            raise ValueError(f"anchor_time must be HH:MM, got {raw!r}")
        return int(parts[0]), int(parts[1])

    async def create_task(self, request: web.Request) -> web.Response:
        """POST /api/tasks — register a scheduled Claude Code task.

        Body (JSON):
            name: Unique task identifier.
            prompt: Claude Code prompt to run on schedule.
            interval_seconds: How often to run (seconds).
            channel_id: Discord channel ID for thread creation.
            working_dir: (optional) Working directory for Claude.
            run_immediately: (optional, default true) Fire on next loop tick.
            anchor_time: (optional) Wall-clock time ``"HH:MM"`` to snap to,
                preventing time drift. When set, next_run_at is calculated as
                the next future occurrence of that time.
            thread_id: (optional) Discord thread ID for follow-up mode.
                When set, the scheduler posts into this existing thread
                instead of creating a new one.
            one_shot: (optional, default false) If true, auto-disable after
                a single execution.
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
            anchor_hour, anchor_minute = self._parse_anchor_time(data.get("anchor_time"))
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)

        # Parse optional follow-up parameters
        raw_thread_id = data.get("thread_id")
        thread_id: int | None = None
        if raw_thread_id is not None:
            with contextlib.suppress(ValueError, TypeError):
                thread_id = int(raw_thread_id)

        one_shot = bool(data.get("one_shot", False))

        try:
            task_id = await self.task_repo.create(  # type: ignore[union-attr]
                name=str(data["name"]),
                prompt=str(data["prompt"]),
                interval_seconds=int(data["interval_seconds"]),
                channel_id=int(data["channel_id"]),
                working_dir=data.get("working_dir"),
                run_immediately=bool(data.get("run_immediately", True)),
                anchor_hour=anchor_hour,
                anchor_minute=anchor_minute,
                thread_id=thread_id,
                one_shot=one_shot,
            )
        except Exception as exc:
            # Most likely a UNIQUE constraint violation on name
            logger.warning("Failed to create task: %s", exc)
            return web.json_response({"error": "Task name already exists"}, status=409)

        logger.info("Task registered via API: id=%d, name=%s", task_id, _sanitize_log(data["name"]))
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
        """PATCH /api/tasks/{id} — update a task.

        Body (JSON, all optional):
            enabled: bool
            prompt: str
            interval_seconds: int
            working_dir: str
            anchor_time: ``"HH:MM"`` to set, or ``null`` to clear
            next_run_at: float (epoch) — manual schedule reset
        """
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

        # anchor_time: "HH:MM" to set, null to clear
        if "anchor_time" in data:
            raw_anchor = data["anchor_time"]
            if raw_anchor is None:
                patch_kwargs["anchor_hour"] = -1  # sentinel: clear
            else:
                try:
                    h, m = self._parse_anchor_time(raw_anchor)
                except ValueError as exc:
                    return web.json_response({"error": str(exc)}, status=400)
                patch_kwargs["anchor_hour"] = h
                patch_kwargs["anchor_minute"] = m

        if patch_kwargs:
            result = await self.task_repo.update(task_id, **patch_kwargs)  # type: ignore[union-attr]
            updated = updated or result

        # Manual next_run_at override
        if "next_run_at" in data:
            await self.task_repo._db_execute(  # type: ignore[union-attr]
                "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
                (float(data["next_run_at"]), task_id),
            )
            updated = True

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
                        "thread_id": m.thread_id,
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

        # thread_id is optional — allows tracing which Discord thread posted the message
        raw_thread_id = data.get("thread_id")
        thread_id: int | None = None
        if raw_thread_id is not None:
            with contextlib.suppress(ValueError, TypeError):
                thread_id = int(raw_thread_id)

        stored = await self.lounge_repo.post(message=message, label=label, thread_id=thread_id)  # type: ignore[union-attr]

        # Forward to Discord lounge channel if configured
        if self.lounge_channel_id:
            await self._send_lounge_to_discord(stored.label, stored.message, stored.posted_at)

        return web.json_response(
            {
                "status": "posted",
                "id": stored.id,
                "label": stored.label,
                "message": stored.message,
                "thread_id": stored.thread_id,
                "posted_at": stored.posted_at,
            },
            status=201,
        )

    # ------------------------------------------------------------------
    # Session spawn endpoint (/api/spawn)
    # ------------------------------------------------------------------

    async def spawn(self, request: web.Request) -> web.Response:
        """POST /api/spawn — create a new Discord thread and optionally start Claude Code.

        Unlike posting a message to the channel directly, this endpoint
        bypasses the ``on_message`` bot-author guard and works even when
        called from within another Claude Code session.

        Body (JSON):
            prompt: The instruction to send to Claude (required).
            channel_id: Parent channel ID (optional; defaults to the
                ``default_channel_id`` configured at startup).
            thread_name: Custom thread title (optional; defaults to the
                first 100 characters of *prompt*).
            auto_start: Whether to immediately start a Claude Code session
                (optional; defaults to ``true``).  When ``false``, only the
                thread and seed message are created — a Claude session will
                start when a user replies in the thread.

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
        auto_start: bool = data.get("auto_start", True)

        try:
            thread = await cog.spawn_session(
                raw,
                prompt,
                thread_name=thread_name,
                auto_start=auto_start,
            )
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
            _sanitize_log(reason),
            _sanitize_log(session_id),
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

    @staticmethod
    def _build_poll(poll_data: dict) -> discord.Poll | web.Response:
        """Build a discord.Poll from API request data.

        Returns a Poll on success, or a web.Response (400) on validation error.
        """
        import discord

        question = poll_data.get("question")
        if not question:
            return web.json_response({"error": "poll.question is required"}, status=400)

        answers = poll_data.get("answers")
        if not answers or len(answers) < 2:
            return web.json_response(
                {"error": "poll.answers must have at least 2 items"}, status=400
            )

        duration_hours = poll_data.get("duration_hours", 24)
        allow_multiselect = poll_data.get("allow_multiselect", False)

        poll = discord.Poll(
            question=question,
            duration=timedelta(hours=duration_hours),
            multiple=allow_multiselect,
        )

        for answer in answers:
            if isinstance(answer, str):
                poll.add_answer(text=answer)
            elif isinstance(answer, dict):
                kwargs: dict = {"text": answer["text"]}
                if "emoji" in answer:
                    kwargs["emoji"] = answer["emoji"]
                poll.add_answer(**kwargs)

        return poll

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
