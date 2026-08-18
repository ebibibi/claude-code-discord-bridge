"""Unified thread search: persistent summaries plus optional transcript bodies.

Two surfaces (the ``/search`` slash command and ``GET /api/search``) share this
orchestrator so their ranking and merge rules stay identical.  Summary hits (the
cheap, always-on tier) come first; when body search is requested, transcript
matches enrich the result set with threads whose *opening prompt* didn't mention
the keyword but whose conversation did.  Discord-specific concerns (deep-links,
embeds) stay in the callers — this layer is frontend-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .transcript_search import search_transcripts


@dataclass(frozen=True)
class ThreadSearchResult:
    """One search hit, from a thread summary or a transcript body."""

    thread_id: int | None
    session_id: str | None
    summary: str | None
    working_dir: str | None
    origin: str | None
    last_used_at: str | None
    snippet: str | None  # body-match excerpt; None for summary-only hits
    source: str  # "summary" or "body"


class _SessionSearchRepo(Protocol):
    """The slice of SessionRepository this orchestrator needs."""

    async def search(
        self, query: str, *, origin: str | None = ..., limit: int = ...
    ) -> list[Any]: ...

    async def get_by_session_id(self, session_id: str) -> Any: ...


async def run_thread_search(
    *,
    session_repo: _SessionSearchRepo,
    query: str,
    origin: str | None = None,
    limit: int = 15,
    include_body: bool = False,
    transcripts_root: str | None = None,
    body_limit: int = 10,
) -> list[ThreadSearchResult]:
    """Search thread summaries and (optionally) transcript bodies.

    Args:
        session_repo: Session store (needs ``search`` and ``get_by_session_id``).
        query: Keyword (case-insensitive substring).
        origin: Filter summary matches by origin ('discord'/'cli').
        limit: Max summary results.
        include_body: When True, also grep local transcripts for the keyword.
        transcripts_root: Directory of ``<session_id>.jsonl`` files.
        body_limit: Max transcript hits considered.
    """
    query = query.strip()
    results: list[ThreadSearchResult] = []
    seen_threads: set[int] = set()

    for record in await session_repo.search(query=query, origin=origin, limit=limit):
        results.append(
            ThreadSearchResult(
                thread_id=record.thread_id,
                session_id=record.session_id,
                summary=record.summary,
                working_dir=record.working_dir,
                origin=record.origin,
                last_used_at=record.last_used_at,
                snippet=None,
                source="summary",
            )
        )
        seen_threads.add(record.thread_id)

    if not (include_body and transcripts_root and query):
        return results

    for hit in await search_transcripts(transcripts_root, query, limit=body_limit):
        record = await session_repo.get_by_session_id(hit.session_id)
        if record is not None:
            if record.thread_id in seen_threads:
                continue  # already surfaced via its summary — don't duplicate
            seen_threads.add(record.thread_id)
            results.append(
                ThreadSearchResult(
                    thread_id=record.thread_id,
                    session_id=record.session_id,
                    summary=record.summary,
                    working_dir=record.working_dir,
                    origin=record.origin,
                    last_used_at=record.last_used_at,
                    snippet=hit.snippet,
                    source="body",
                )
            )
        else:
            # Transcript with no Discord thread (a CLI run or an older
            # resume-chain fragment). Still useful: it can be reopened with
            # ``claude --resume <session_id>``.
            results.append(
                ThreadSearchResult(
                    thread_id=None,
                    session_id=hit.session_id,
                    summary=None,
                    working_dir=None,
                    origin=None,
                    last_used_at=None,
                    snippet=hit.snippet,
                    source="body",
                )
            )

    return results
