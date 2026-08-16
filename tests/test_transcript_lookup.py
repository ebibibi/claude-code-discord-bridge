"""Finding one session's transcript by id.

A thread can be deleted; its transcript cannot. Everything that wants to say
something about a finished conversation after the thread is gone has to get
from ``session_id`` to a file on disk, and the project directory that file
lives under is derived from the working directory, which the caller may not
know. So the lookup searches, rather than reconstructing a path.
"""

from __future__ import annotations

import json

from claude_code_core.transcript_search import find_transcript

_SID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_OTHER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _write(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def test_finds_transcript_in_a_project_subdirectory(tmp_path) -> None:
    _write(tmp_path / "-home-ebi" / f"{_SID}.jsonl", "hello")
    assert find_transcript(_SID, str(tmp_path)) == str(tmp_path / "-home-ebi" / f"{_SID}.jsonl")


def test_searches_every_project_directory(tmp_path) -> None:
    _write(tmp_path / "-home-ebi" / f"{_OTHER}.jsonl", "wrong one")
    _write(tmp_path / "-home-ebi-scheduler" / f"{_SID}.jsonl", "right one")
    found = find_transcript(_SID, str(tmp_path))
    assert found is not None
    assert found.endswith(f"-home-ebi-scheduler/{_SID}.jsonl")


def test_unknown_session_is_none(tmp_path) -> None:
    _write(tmp_path / "-home-ebi" / f"{_OTHER}.jsonl", "hello")
    assert find_transcript(_SID, str(tmp_path)) is None


def test_missing_root_is_none() -> None:
    assert find_transcript(_SID, "/nonexistent/path/for/tests") is None


def test_no_root_is_none() -> None:
    assert find_transcript(_SID, None) is None


def test_rejects_a_session_id_that_is_not_a_session_id(tmp_path) -> None:
    """The id reaches a filesystem glob, so anything path-shaped must not."""
    _write(tmp_path / "-home-ebi" / f"{_SID}.jsonl", "hello")
    for hostile in ("../../etc/passwd", "*", "", "a" * 40, "../" + _SID):
        assert find_transcript(hostile, str(tmp_path)) is None
