"""tests/test_thread_completion.py

Unit tests for ThreadCompletionCog — the Cog that treats "the user deleted the
thread" as "that work is finished" and files a record for it.

The interesting constraint is that by the time the delete event arrives, the
thread's messages are already unreachable. Everything the record says has to
come from what ccdb kept: the session row, and the transcript on disk.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Set required env vars before the module under test is imported.
os.environ.setdefault("THREAD_COMPLETION_CHANNEL_ID", "333333333333333333")

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402

from examples.ebibot.cogs.thread_completion import (  # noqa: E402
    CompletionRecord,
    build_prompt,
    collect_records,
    load_template,
    write_manifest,
)


def _session(thread_id: int, session_id: str, summary: str | None = "やったこと") -> MagicMock:
    rec = MagicMock()
    rec.thread_id = thread_id
    rec.session_id = session_id
    rec.summary = summary
    rec.working_dir = "/home/ebi"
    rec.last_used_at = "2026-08-16 10:00:00"
    return rec


def _repo(records: dict[int, MagicMock]) -> MagicMock:
    repo = MagicMock()
    repo.get = AsyncMock(side_effect=lambda tid: records.get(tid))
    return repo


class TestCollectRecords:
    @pytest.mark.asyncio
    async def test_builds_a_record_from_the_session_row(self, tmp_path) -> None:
        sid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        proj = tmp_path / "-home-ebi"
        proj.mkdir()
        (proj / f"{sid}.jsonl").write_text("{}\n", encoding="utf-8")

        got = await collect_records([111], _repo({111: _session(111, sid)}), str(tmp_path))

        assert len(got) == 1
        assert got[0].thread_id == 111
        assert got[0].session_id == sid
        assert got[0].transcript_path is not None
        assert got[0].transcript_path.endswith(f"{sid}.jsonl")

    @pytest.mark.asyncio
    async def test_threads_with_no_session_are_dropped(self, tmp_path) -> None:
        """Notification threads (おはよう, scheduler alerts) never held a session."""
        got = await collect_records([111, 222], _repo({111: _session(111, "a" * 8)}), str(tmp_path))
        assert [r.thread_id for r in got] == [111]

    @pytest.mark.asyncio
    async def test_a_missing_transcript_still_yields_a_record(self, tmp_path) -> None:
        """The session summary alone is worth filing; don't drop the whole record."""
        sid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        got = await collect_records([111], _repo({111: _session(111, sid)}), str(tmp_path))
        assert len(got) == 1
        assert got[0].transcript_path is None

    @pytest.mark.asyncio
    async def test_a_broken_repo_lookup_does_not_lose_the_other_threads(self, tmp_path) -> None:
        repo = MagicMock()

        async def flaky(tid: int):
            if tid == 111:
                raise RuntimeError("db is locked")
            return _session(tid, "dddddddd-dddd-dddd-dddd-dddddddddddd")

        repo.get = AsyncMock(side_effect=flaky)
        got = await collect_records([111, 222], repo, str(tmp_path))
        assert [r.thread_id for r in got] == [222]

    @pytest.mark.asyncio
    async def test_duplicate_ids_are_recorded_once(self, tmp_path) -> None:
        sid = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        got = await collect_records([111, 111], _repo({111: _session(111, sid)}), str(tmp_path))
        assert len(got) == 1


class TestWriteManifest:
    def test_manifest_is_readable_json(self, tmp_path) -> None:
        rec = CompletionRecord(
            thread_id=111,
            session_id="s",
            summary="要約",
            working_dir="/home/ebi",
            last_used_at="2026-08-16 10:00:00",
            transcript_path="/t.jsonl",
        )
        path = write_manifest([rec], str(tmp_path), "2026-08-16T12-00-00")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        assert data["deleted_at"] == "2026-08-16T12-00-00"
        assert data["threads"][0]["thread_id"] == 111
        assert data["threads"][0]["transcript_path"] == "/t.jsonl"

    def test_manifest_filename_is_unique_per_flush(self, tmp_path) -> None:
        rec = CompletionRecord(111, "s", None, None, None, None)
        a = write_manifest([rec], str(tmp_path), "2026-08-16T12-00-00")
        b = write_manifest([rec], str(tmp_path), "2026-08-16T12-00-01")
        assert a != b


class TestBuildPrompt:
    def test_prompt_points_at_the_manifest_and_never_inlines_the_body(self) -> None:
        rec = CompletionRecord(
            thread_id=111,
            session_id="s",
            summary="秘密の顧客名がここに入る",
            working_dir="/home/ebi",
            last_used_at="2026-08-16 10:00:00",
            transcript_path="/t.jsonl",
        )
        prompt = build_prompt("/tmp/m.json", [rec])
        assert "/tmp/m.json" in prompt
        # The prompt is an instruction, not a data dump: the manifest carries the
        # content so a long batch can't blow up the prompt or leak into logs.
        assert "秘密の顧客名がここに入る" not in prompt

    def test_prompt_states_the_count(self) -> None:
        recs = [CompletionRecord(i, "s", None, None, None, None) for i in range(3)]
        assert "3" in build_prompt("/tmp/m.json", recs)


class TestLoadTemplate:
    """The instance's wording lives outside this repository, which is public."""

    def test_no_file_configured_falls_back_to_the_generic_prompt(self) -> None:
        template = load_template("")
        assert "{count}" in template and "{manifest}" in template
        rendered = build_prompt(
            "/tmp/m.json", [CompletionRecord(1, "s", None, None, None, None)], template
        )
        assert "{" not in rendered  # every placeholder was filled
        assert "deleted" in rendered.lower()

    def test_an_external_template_is_used_verbatim(self, tmp_path) -> None:
        path = tmp_path / "prompt.md"
        path.write_text("{count}件を{manifest}から記録して", encoding="utf-8")
        prompt = build_prompt(
            "/tmp/m.json",
            [CompletionRecord(1, "s", None, None, None, None)],
            load_template(str(path)),
        )
        assert prompt == "1件を/tmp/m.jsonから記録して"

    def test_an_unreadable_template_falls_back_instead_of_losing_the_batch(self) -> None:
        assert load_template("/nonexistent/prompt.md") == load_template("")
