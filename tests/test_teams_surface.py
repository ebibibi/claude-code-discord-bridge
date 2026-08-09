"""``TeamsSurface`` against a recording connector.

The fake here is the *transport*, not the surface: every assertion below is
about what the shipped `TeamsSurface` decided to send. That matters more than
usual for this class, because almost all of its behaviour is a decision about
how many requests to spend.
"""

from __future__ import annotations

import asyncio
from typing import Any

from claude_code_core.frontend import (
    ActivitySpec,
    Choice,
    ChoicePrompt,
    FormField,
    FormPrompt,
    Notice,
    NoticeLevel,
    OutboundFile,
    StatusKind,
)
from claude_teams.capabilities import TEAMS_CAPABILITIES
from claude_teams.conversation import ConversationRef
from claude_teams.pacer import UpdatePacer
from claude_teams.surface import TeamsSurface

REF = ConversationRef(
    service_url="https://smba.trafficmanager.net/emea/",
    conversation_id="19:abc@thread.tacv2;messageid=1481567603816",
)
THREAD_KEY = 9_007_199_254_740_993


class RecordingConnector:
    """Remembers every activity sent and every edit made."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self._next = 0

    async def send_activity(self, ref: ConversationRef, body: dict[str, Any]) -> str:
        self.sent.append(body)
        self._next += 1
        return f"activity-{self._next}"

    async def update_activity(
        self, ref: ConversationRef, activity_id: str, body: dict[str, Any]
    ) -> None:
        self.updated.append((activity_id, body))

    @property
    def texts(self) -> list[str]:
        return [b["text"] for b in self.sent if "text" in b]

    @property
    def cards(self) -> list[dict[str, Any]]:
        return [b for b in self.sent if "attachments" in b]


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds
        await asyncio.sleep(0)


def build(connector: RecordingConnector, clock: FakeClock | None = None) -> TeamsSurface:
    clock = clock or FakeClock()
    return TeamsSurface(
        thread_key=THREAD_KEY,
        ref=REF,
        connector=connector,
        title="Fix the parser",
        pacer=UpdatePacer(TEAMS_CAPABILITIES.min_update_interval, now=clock.now, sleep=clock.sleep),
    )


class TestIdentity:
    def test_it_reports_its_own_platform_and_conversation(self) -> None:
        s = build(RecordingConnector())
        assert s.frontend == "teams"
        assert s.external_id == REF.conversation_id
        assert s.thread_key == THREAD_KEY
        assert s.capabilities is TEAMS_CAPABILITIES


class TestSendText:
    async def test_a_long_answer_arrives_as_one_message(self) -> None:
        # The visible payoff of driving the chunker from capabilities: at
        # 80,000 chars this is one message where Discord needs fifteen.
        connector = RecordingConnector()
        s = build(connector)
        await s.send_text("word " * 4000)
        assert len(connector.texts) == 1

    async def test_an_answer_past_the_limit_is_split(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        await s.send_text("x" * (TEAMS_CAPABILITIES.max_message_chars * 2))
        assert len(connector.texts) >= 2
        for text in connector.texts:
            assert len(text) <= TEAMS_CAPABILITIES.max_message_chars

    async def test_empty_text_sends_nothing(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        await s.send_text("")
        await s.send_text("   \n  ")
        assert connector.sent == []


class TestNotices:
    async def test_every_level_produces_something(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        for level in NoticeLevel:
            await s.send_notice(Notice(level=level, title="t", body="b"))
        assert len(connector.texts) == len(NoticeLevel)

    async def test_a_monospace_body_is_fenced(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        await s.send_notice(Notice(level=NoticeLevel.INFO, body="a b c", monospace_body=True))
        assert "```" in connector.texts[0]

    async def test_fields_are_rendered(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        await s.send_notice(Notice(level=NoticeLevel.INFO, fields=(("Model", "opus"),)))
        assert "opus" in connector.texts[0]


class TestTheCard:
    async def test_the_first_activity_creates_one_card(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        await s.open_activity(ActivitySpec(kind="tool", title="Read", detail="a.py"))
        assert len(connector.cards) == 1
        assert connector.updated == []

    async def test_later_changes_edit_that_card_rather_than_posting_another(self) -> None:
        # This is the whole Teams design in one assertion. A message per tool
        # call would burn the conversation's hourly budget on scrollback.
        connector = RecordingConnector()
        s = build(connector)
        handle = await s.open_activity(ActivitySpec(kind="tool", title="Read"))
        await handle.complete("42 lines")
        await s.close()
        assert len(connector.cards) == 1
        assert len(connector.updated) >= 1

    async def test_changes_inside_one_interval_cost_one_update(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        await s.set_status(StatusKind.THINKING)  # first paint, immediate
        await s.set_status(StatusKind.TOOL_READ)
        await s.set_status(StatusKind.TOOL_EDIT)
        await s.set_status(StatusKind.TOOL_COMMAND)
        await s.close()
        assert len(connector.cards) == 1
        assert len(connector.updated) == 1, "three status changes must not cost three requests"

    async def test_the_coalesced_update_shows_the_state_at_send_time(self) -> None:
        # The closure has to read the surface when it runs, not when it was
        # queued — otherwise the card lands showing whichever change happened
        # to win the race rather than what is true.
        connector = RecordingConnector()
        s = build(connector)
        await s.set_status(StatusKind.THINKING)
        await s.set_status(StatusKind.TOOL_READ)
        await s.set_status(StatusKind.ERROR)
        await s.close()
        rendered = str(connector.updated[-1][1])
        assert "Error" in rendered
        assert "Reading" not in rendered

    async def test_repeating_the_same_status_costs_nothing(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        await s.set_status(StatusKind.THINKING)
        await s.set_status(StatusKind.THINKING)
        await s.close()
        assert connector.updated == []

    async def test_completing_an_activity_twice_is_harmless(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        handle = await s.open_activity(ActivitySpec(kind="tool", title="Read"))
        await handle.complete("ok")
        await handle.complete("ok")
        await handle.cancel()
        await s.close()

    async def test_a_failed_tool_is_marked_as_failed(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        handle = await s.open_activity(ActivitySpec(kind="tool", title="Bash"))
        await handle.complete("exit 1", ok=False)
        await s.close()
        assert "✗" in str(connector.updated[-1][1])

    async def test_rename_retitles_the_card(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        await s.set_status(StatusKind.THINKING)
        await s.rename("A better title")
        await s.close()
        assert "A better title" in str(connector.updated[-1][1])


class TestStreaming:
    async def test_the_first_delta_posts_and_the_rest_edit(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        stream = s.open_stream()
        assert not stream.has_content

        await stream.append("Hello, ")
        assert stream.has_content
        await stream.append("world")
        final = await stream.finalize()

        assert final == "Hello, world"
        assert len(connector.texts) == 1, "streaming must not post a message per delta"
        assert connector.updated, "the growing answer has to be shown somewhere"
        assert "Hello, world" in str(connector.updated[-1][1])

    async def test_finalize_is_idempotent(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        stream = s.open_stream()
        await stream.append("done")
        first = await stream.finalize()
        before = len(connector.sent) + len(connector.updated)
        second = await stream.finalize()
        assert first == second
        assert len(connector.sent) + len(connector.updated) == before

    async def test_a_transform_applies_to_what_is_shown(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        stream = s.open_stream()
        await stream.append("hello")
        final = await stream.finalize(lambda t: t.upper())
        assert final == "HELLO"
        assert "HELLO" in str(connector.updated[-1][1])

    async def test_an_empty_stream_posts_nothing(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        stream = s.open_stream()
        assert await stream.finalize() == ""
        assert connector.sent == []

    async def test_overflow_starts_a_new_message_without_repainting_the_first(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        stream = s.open_stream()
        await stream.append("x" * (TEAMS_CAPABILITIES.max_message_chars + 100))
        await stream.finalize()

        assert len(connector.texts) == 2, "the overflow needs a message of its own"
        edited_ids = {activity_id for activity_id, _ in connector.updated}
        assert connector.texts[0][:10] not in [b.get("text", "")[:10] for _, b in connector.updated]
        assert len(edited_ids) <= 1, "a finished message must not be repainted"

    async def test_the_card_and_the_stream_do_not_displace_each_other(self) -> None:
        # Both are queued inside one interval. Coalescing on a single key would
        # drop one of them, and the answer would silently stop growing.
        connector = RecordingConnector()
        s = build(connector)
        stream = s.open_stream()
        await stream.append("first")  # immediate: posts the message
        await stream.append(" and more")  # queued under the stream key
        await s.set_status(StatusKind.TOOL_READ)  # queued under the card key
        await s.close()

        assert any("and more" in str(body) for _, body in connector.updated)
        assert connector.cards, "the card still has to be painted"


class TestFilesAreNotClaimed:
    async def test_the_message_says_the_contents_were_not_sent(self) -> None:
        # A silent no-op would leave a session believing its output was handed
        # over. Naming the gap is the only honest option until upload works.
        connector = RecordingConnector()
        s = build(connector)
        await s.deliver_files(
            [
                OutboundFile(display_name="a.txt", blob=b"x"),
                OutboundFile(display_name="b.png", blob=b"y"),
            ]
        )
        text = connector.texts[0]
        assert "a.txt" in text and "b.png" in text
        assert "not" in text.lower()

    async def test_an_empty_list_sends_nothing(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        await s.deliver_files([])
        assert connector.sent == []


class TestPromptsPostAnAnswerableCard:
    async def test_a_choice_prompt_posts_a_card_with_an_action_per_choice(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        task = asyncio.create_task(
            s.prompt_choice(
                ChoicePrompt(
                    question="Run it?",
                    choices=(
                        Choice(value="allow", label="Allow"),
                        Choice(value="deny", label="Deny"),
                    ),
                    default_on_timeout="deny",
                )
            )
        )
        await asyncio.sleep(0)
        card = connector.cards[0]["attachments"][0]["content"]
        assert [a["title"] for a in card["actions"]] == ["Allow", "Deny"]

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_a_form_prompt_posts_an_input_per_field(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        task = asyncio.create_task(
            s.prompt_form(
                FormPrompt(
                    title="Details",
                    fields=(FormField(key="name", label="Name", kind="text"),),
                )
            )
        )
        await asyncio.sleep(0)
        card = connector.cards[0]["attachments"][0]["content"]
        assert any(b.get("id") == "name" for b in card["body"])

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_prompt_url_reports_that_it_was_not_confirmed(self) -> None:
        connector = RecordingConnector()
        s = build(connector)
        assert await s.prompt_url("Log in", "https://example.com") is False
        assert "https://example.com" in connector.texts[0]


class TestInterrupt:
    async def test_stop_appears_on_the_card_and_disabling_removes_it(self) -> None:
        async def on_stop() -> None:
            return None

        connector = RecordingConnector()
        s = build(connector)
        handle = await s.offer_interrupt(on_stop)

        card = connector.cards[0]["attachments"][0]["content"]
        assert [a["title"] for a in card["actions"]] == ["Stop"]

        await handle.disable()
        await s.close()
        assert not connector.updated[-1][1]["attachments"][0]["content"].get("actions")

    async def test_disabling_twice_is_harmless_and_stops_honouring_the_id(self) -> None:
        # The session-end path and the user pressing Stop both reach disable().
        # A Stop that still worked afterwards would interrupt whatever ran next.
        fired: list[int] = []

        async def on_stop() -> None:
            fired.append(1)

        connector = RecordingConnector()
        s = build(connector)
        handle = await s.offer_interrupt(on_stop)
        action_id = connector.cards[0]["attachments"][0]["content"]["actions"][0]["data"][
            "ccdb_prompt"
        ]

        await handle.disable()
        await handle.disable()
        assert not s.interactions.resolve(s.external_id, {"ccdb_prompt": action_id})
        await asyncio.sleep(0)
        assert fired == []
        await s.close()


class TestTranscript:
    async def test_history_is_not_available(self) -> None:
        s = build(RecordingConnector())
        assert await s.recent_transcript(7) is None
