"""The session card — Teams' answer to Discord's column of embeds.

Discord posts one embed per tool call because editing is cheap and there is no
hourly ceiling. Teams has 1,800 operations per hour per conversation, so the
same design would spend a long session's whole budget on scrollback. One card
that keeps up to date costs one slot per change however many things changed.

These tests pin the parts of that card a wrong value would quietly break: the
size Teams refuses, the ordering that decides what a user sees, and the actions
that must not appear before something can handle them.
"""

from __future__ import annotations

import json

import pytest

from claude_code_core.frontend import StatusKind
from claude_teams.cards import MAX_CARD_BYTES, ActivityLine, SessionCard


def card(**overrides: object) -> SessionCard:
    kwargs: dict[str, object] = {"title": "Fix the parser"}
    kwargs.update(overrides)
    return SessionCard(**kwargs)  # type: ignore[arg-type]


def body_text(attachment: dict) -> str:
    return json.dumps(attachment)


class TestShape:
    def test_it_is_an_adaptive_card_attachment(self) -> None:
        attachment = card().to_attachment()
        assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive"
        assert attachment["content"]["type"] == "AdaptiveCard"

    def test_the_title_is_shown(self) -> None:
        assert "Fix the parser" in body_text(card().to_attachment())

    def test_a_card_without_a_title_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="title"):
            SessionCard(title="")


class TestStatus:
    def test_every_status_renders(self) -> None:
        # StatusKind is added to over time. A status with no label would render
        # as a blank row rather than raising, which is how a card silently goes
        # empty in production.
        for status in StatusKind:
            rendered = body_text(card(status=status).to_attachment())
            assert rendered.strip(), f"{status} rendered nothing"
            assert "None" not in rendered, f"{status} leaked a Python None into the card"

    def test_no_status_is_a_valid_card(self) -> None:
        assert card(status=None).to_attachment()["content"]["body"]


class TestActivities:
    def test_activities_appear_in_order(self) -> None:
        lines = (
            ActivityLine(title="Read", detail="a.py", state="done"),
            ActivityLine(title="Bash", detail="pytest", state="running"),
        )
        rendered = body_text(card(activities=lines).to_attachment())
        assert rendered.index("Read") < rendered.index("Bash")

    def test_only_the_most_recent_activities_are_kept(self) -> None:
        # An unbounded list is how a long session's card grows past the size
        # Teams accepts, and the failure is a rejected update — the card stops
        # changing and nothing says why.
        lines = tuple(ActivityLine(title=f"Tool{i}", state="done") for i in range(50))
        rendered = body_text(card(activities=lines, max_activities=5).to_attachment())
        assert "Tool49" in rendered, "the newest activity must survive"
        assert "Tool0" not in rendered, "the oldest should have been dropped"

    def test_a_long_detail_is_truncated_rather_than_dropped(self) -> None:
        line = ActivityLine(title="Bash", detail="x" * 5000, state="running")
        rendered = body_text(card(activities=(line,)).to_attachment())
        assert "Bash" in rendered
        assert len(rendered) < 5000

    def test_a_failed_activity_is_distinguishable_from_a_finished_one(self) -> None:
        ok = body_text(card(activities=(ActivityLine(title="T", state="done"),)).to_attachment())
        bad = body_text(card(activities=(ActivityLine(title="T", state="failed"),)).to_attachment())
        assert ok != bad, "a failure that looks like a success is worse than no card"


class TestSize:
    def test_a_full_card_stays_under_the_limit_teams_accepts(self) -> None:
        # Teams rejects a card payload over 28 KB. Rejection is invisible from
        # here: the update fails, the card freezes on its last good state, and
        # the session appears to stop working.
        lines = tuple(
            ActivityLine(title=f"Tool{i}" * 20, detail="d" * 400, state="running")
            for i in range(40)
        )
        payload = json.dumps(card(title="T" * 300, activities=lines).to_attachment())
        assert len(payload.encode()) <= MAX_CARD_BYTES


class TestActionsAreNotClaimedEarly:
    def test_no_action_is_rendered_yet(self) -> None:
        # A Stop button that nothing routes is worse than no button: Teams
        # shows the user an error when the action goes unanswered. The control
        # appears in the change that can handle its invoke.
        content = card().to_attachment()["content"]
        assert not content.get("actions"), "an unroutable action must not be offered"
