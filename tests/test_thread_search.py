"""Tests for run_thread_search — summary + optional transcript-body merge."""

from __future__ import annotations

import json

import pytest

from claude_code_core.session_repo import SessionRepository
from claude_code_core.thread_search import run_thread_search
from claude_discord.database.models import init_db

_SID_MAPPED = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_SID_ORPHAN = "cccccccc-cccc-cccc-cccc-cccccccccccc"


@pytest.fixture
async def repo(tmp_path) -> SessionRepository:
    db_path = str(tmp_path / "sessions.db")
    await init_db(db_path)
    r = SessionRepository(db_path)
    await r.save(
        thread_id=1, session_id="sess-1", summary="Design the search feature", origin="discord"
    )
    await r.save(
        thread_id=2,
        session_id=_SID_MAPPED,
        summary="Opening prompt about weather",
        origin="discord",
    )
    return r


def _write_transcript(path, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "type": "user",
                    "message": {"role": "user", "content": [{"type": "text", "text": text}]},
                },
                ensure_ascii=False,
            )
            + "\n"
        )


async def test_summary_only_when_body_disabled(repo: SessionRepository) -> None:
    results = await run_thread_search(session_repo=repo, query="search", include_body=False)
    assert [r.thread_id for r in results] == [1]
    assert results[0].source == "summary"


async def test_body_hit_maps_to_thread(repo: SessionRepository, tmp_path) -> None:
    # A keyword that appears mid-conversation (not in the opening summary).
    _write_transcript(tmp_path / f"{_SID_MAPPED}.jsonl", "we then reconfigured the DNS records")
    results = await run_thread_search(
        session_repo=repo,
        query="DNS records",
        include_body=True,
        transcripts_root=str(tmp_path),
    )
    body = [r for r in results if r.source == "body"]
    assert len(body) == 1
    assert body[0].thread_id == 2  # mapped via session_id
    assert "DNS records" in body[0].snippet


async def test_body_hit_without_session_record_is_orphan(repo: SessionRepository, tmp_path) -> None:
    _write_transcript(tmp_path / f"{_SID_ORPHAN}.jsonl", "orphaned CLI run mentioning kubernetes")
    results = await run_thread_search(
        session_repo=repo,
        query="kubernetes",
        include_body=True,
        transcripts_root=str(tmp_path),
    )
    orphans = [r for r in results if r.thread_id is None]
    assert len(orphans) == 1
    assert orphans[0].session_id == _SID_ORPHAN
    assert orphans[0].source == "body"


async def test_body_does_not_duplicate_existing_summary_thread(
    repo: SessionRepository, tmp_path
) -> None:
    # Thread 1 already matches by summary; its transcript also contains the word.
    _write_transcript(tmp_path / "sess-1.jsonl", "search appears in the body too")
    results = await run_thread_search(
        session_repo=repo,
        query="search",
        include_body=True,
        transcripts_root=str(tmp_path),
    )
    thread_ids = [r.thread_id for r in results if r.thread_id == 1]
    assert len(thread_ids) == 1  # not duplicated
