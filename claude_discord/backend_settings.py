"""Persistent, runtime-mutable backend/model selection.

Reads and writes the current backend (claude/codex) and per-backend
model preference to ``SettingsRepository`` (sqlite key-value store).

Resolution order for any field:
    1. Thread-scoped override (when ``thread_id`` is given)
    2. Global setting
    3. Environment default (passed to constructor)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .database.settings_repo import SettingsRepository

logger = logging.getLogger(__name__)

# Valid backend names. Keep in sync with claude_code_core.backend.create_backend().
ALL_BACKENDS = ("claude", "codex")

# Settings keys
BACKEND_GLOBAL = "backend.global"
BACKEND_THREAD_PREFIX = "backend.thread."  # + thread_id
MODEL_GLOBAL_PREFIX = "model.global."  # + backend
MODEL_THREAD_PREFIX = "model.thread."  # + thread_id + "." + backend


class BackendSettings:
    """Thin wrapper around SettingsRepository that resolves backend/model."""

    def __init__(
        self,
        repo: SettingsRepository,
        *,
        env_backend: str,
        env_model_for_claude: str,
        env_model_for_codex: str,
    ) -> None:
        self.repo = repo
        self._env_backend = env_backend if env_backend in ALL_BACKENDS else "claude"
        self._env_model = {
            "claude": env_model_for_claude or "",
            "codex": env_model_for_codex or "",
        }

    # ── Resolution ──────────────────────────────────────────

    async def current_backend(self, thread_id: int | None = None) -> str:
        """Return the active backend for the given thread (or globally)."""
        if thread_id is not None:
            v = await self.repo.get(f"{BACKEND_THREAD_PREFIX}{thread_id}")
            if v in ALL_BACKENDS:
                return v
        v = await self.repo.get(BACKEND_GLOBAL)
        if v in ALL_BACKENDS:
            return v
        return self._env_backend

    async def current_model(self, backend: str, thread_id: int | None = None) -> str | None:
        """Return the model for the given backend, or None if no override.

        When ``None`` is returned the caller should fall back to the
        backend factorys built-in default (e.g. "sonnet" / "gpt-5.4").
        """
        if backend not in ALL_BACKENDS:
            return None
        if thread_id is not None:
            v = await self.repo.get(f"{MODEL_THREAD_PREFIX}{thread_id}.{backend}")
            if v:
                return v
        v = await self.repo.get(f"{MODEL_GLOBAL_PREFIX}{backend}")
        if v:
            return v
        return self._env_model.get(backend) or None

    # ── Mutation ────────────────────────────────────────────

    async def set_backend(self, backend: str, *, thread_id: int | None = None) -> None:
        if backend not in ALL_BACKENDS:
            raise ValueError(f"unknown backend {backend!r}")
        if thread_id is not None:
            await self.repo.set(f"{BACKEND_THREAD_PREFIX}{thread_id}", backend)
            logger.info("backend set: thread=%d -> %s", thread_id, backend)
        else:
            await self.repo.set(BACKEND_GLOBAL, backend)
            logger.info("backend set: global -> %s", backend)

    async def set_model(self, backend: str, model: str, *, thread_id: int | None = None) -> None:
        if backend not in ALL_BACKENDS:
            raise ValueError(f"unknown backend {backend!r}")
        if not model:
            raise ValueError("model must not be empty")
        if thread_id is not None:
            await self.repo.set(f"{MODEL_THREAD_PREFIX}{thread_id}.{backend}", model)
            logger.info("model set: thread=%d backend=%s -> %s", thread_id, backend, model)
        else:
            await self.repo.set(f"{MODEL_GLOBAL_PREFIX}{backend}", model)
            logger.info("model set: global backend=%s -> %s", backend, model)

    async def clear_thread_overrides(self, thread_id: int) -> int:
        """Remove all thread-scoped overrides. Returns count deleted."""
        deleted = 0
        if await self.repo.delete(f"{BACKEND_THREAD_PREFIX}{thread_id}"):
            deleted += 1
        for b in ALL_BACKENDS:
            if await self.repo.delete(f"{MODEL_THREAD_PREFIX}{thread_id}.{b}"):
                deleted += 1
        return deleted
