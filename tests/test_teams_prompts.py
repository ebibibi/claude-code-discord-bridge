"""Answering a prompt from Teams — and what happens when nobody does.

The second half is the important half. The shared conformance contract
deliberately does not check ``default_on_timeout``, because from outside "the
user denied it" and "the surface invented a denial" are the same return value
and no external check can force nobody to answer. Here the answer *can* be
withheld, so this is where fail-closed is proved.
"""

from __future__ import annotations

import asyncio
from typing import Any

from claude_code_core.frontend import (
    Choice,
    ChoicePrompt,
    FormField,
    FormPrompt,
)
from claude_teams.conversation import ConversationRef
from claude_teams.interactions import InteractionRegistry
from claude_teams.pacer import UpdatePacer
from claude_teams.surface import TeamsSurface

REF = ConversationRef(
    service_url="https://smba.trafficmanager.net/emea/",
    conversation_id="19:abc@thread.tacv2",
)
PERMISSION = ChoicePrompt(
    question="Run `rm -rf build/`?",
    header="Permission",
    choices=(
        Choice(value="allow", label="Allow", style="positive"),
        Choice(value="deny", label="Deny", style="destructive"),
    ),
    default_on_timeout="deny",
    timeout_seconds=0.05,
)


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail

    async def send_activity(self, ref: ConversationRef, body: dict[str, Any]) -> str:
        if self.fail:
            raise RuntimeError("Teams said no")
        self.sent.append(body)
        return f"activity-{len(self.sent)}"

    async def update_activity(
        self, ref: ConversationRef, activity_id: str, body: dict[str, Any]
    ) -> None:
        return None

    def action_data(self, index: int = 0) -> dict[str, Any]:
        card = self.sent[index]["attachments"][0]["content"]
        return card["actions"][0]["data"]

    def prompt_id(self, index: int = 0) -> str:
        content = self.sent[index]["attachments"][0]["content"]
        for action in content["actions"]:
            if "ccdb_prompt" in action["data"]:
                return action["data"]["ccdb_prompt"]
        raise AssertionError("no prompt id on the card")


def build(recorder: Recorder, registry: InteractionRegistry) -> TeamsSurface:
    return TeamsSurface(
        thread_key=9_007_199_254_740_993,
        ref=REF,
        connector=recorder,
        pacer=UpdatePacer(0.001),
        interactions=registry,
    )


class TestAnsweringFromTeams:
    async def test_pressing_a_choice_resolves_the_waiting_caller(self) -> None:
        recorder, registry = Recorder(), InteractionRegistry()
        surface = build(recorder, registry)

        task = asyncio.create_task(surface.prompt_choice(PERMISSION))
        await asyncio.sleep(0)
        assert registry.resolve(
            REF.conversation_id, {"ccdb_prompt": recorder.prompt_id(), "ccdb_value": "allow"}
        )
        assert await task == ("allow",)

    async def test_a_form_submit_returns_only_the_declared_fields(self) -> None:
        recorder, registry = Recorder(), InteractionRegistry()
        surface = build(recorder, registry)
        prompt = FormPrompt(
            title="Details",
            fields=(
                FormField(key="name", label="Name", kind="text"),
                FormField(key="note", label="Note", kind="multiline"),
            ),
            timeout_seconds=1.0,
        )

        task = asyncio.create_task(surface.prompt_form(prompt))
        await asyncio.sleep(0)
        assert registry.resolve(
            REF.conversation_id,
            {
                "ccdb_prompt": recorder.prompt_id(),
                "name": "Ada",
                "note": "hi",
                "injected": "nope",
            },
        )
        assert await task == {"name": "Ada", "note": "hi"}


class TestFailClosed:
    async def test_an_unanswered_permission_request_denies(self) -> None:
        # The whole reason default_on_timeout exists. An unattended session
        # must not sit forever, and it must not proceed either.
        recorder, registry = Recorder(), InteractionRegistry()
        surface = build(recorder, registry)

        assert await surface.prompt_choice(PERMISSION) == ("deny",)

    async def test_a_prompt_that_could_not_be_posted_also_denies(self) -> None:
        # "Nobody could see it" must not be safer to ignore than "nobody
        # answered it" — otherwise an outage becomes an approval.
        recorder, registry = Recorder(fail=True), InteractionRegistry()
        surface = build(recorder, registry)

        assert await surface.prompt_choice(PERMISSION) == ("deny",)

    async def test_a_prompt_with_no_default_returns_unanswered(self) -> None:
        recorder, registry = Recorder(), InteractionRegistry()
        surface = build(recorder, registry)
        prompt = ChoicePrompt(
            question="Which one?",
            choices=(Choice(value="a", label="A"),),
            timeout_seconds=0.05,
        )
        assert await surface.prompt_choice(prompt) is None

    async def test_a_timed_out_prompt_can_no_longer_be_answered(self) -> None:
        # Otherwise a press that lands after the session already denied would
        # resolve nothing visible but leave the registry holding a live prompt.
        recorder, registry = Recorder(), InteractionRegistry()
        surface = build(recorder, registry)

        await surface.prompt_choice(PERMISSION)
        assert not registry.resolve(
            REF.conversation_id, {"ccdb_prompt": recorder.prompt_id(), "ccdb_value": "allow"}
        )
        assert registry.pending_count == 0


class TestIsolationBetweenConversations:
    async def test_an_answer_from_another_conversation_does_not_apply(self) -> None:
        # Same registry, two conversations — which is how a deployment runs.
        # A prompt answerable from anywhere would let one channel approve
        # another channel's tool run.
        recorder, registry = Recorder(), InteractionRegistry()
        surface = build(recorder, registry)

        task = asyncio.create_task(surface.prompt_choice(PERMISSION))
        await asyncio.sleep(0)
        assert not registry.resolve(
            "19:somewhere-else@thread.tacv2",
            {"ccdb_prompt": recorder.prompt_id(), "ccdb_value": "allow"},
        )
        assert await task == ("deny",), "the intruder's press must not become an approval"


class TestCardShape:
    async def test_a_long_choice_list_becomes_a_dropdown(self) -> None:
        # Fifteen buttons is not a UI. Teams wraps them badly and the answer
        # a user wants is off the bottom of the card.
        recorder, registry = Recorder(), InteractionRegistry()
        surface = build(recorder, registry)
        prompt = ChoicePrompt(
            question="Pick",
            choices=tuple(Choice(value=f"v{i}", label=f"Option {i}") for i in range(12)),
            timeout_seconds=0.05,
        )

        await surface.prompt_choice(prompt)
        content = recorder.sent[0]["attachments"][0]["content"]
        assert any(b.get("type") == "Input.ChoiceSet" for b in content["body"])
        assert len(content["actions"]) == 1

    async def test_multi_select_uses_a_multi_select_input(self) -> None:
        recorder, registry = Recorder(), InteractionRegistry()
        surface = build(recorder, registry)
        prompt = ChoicePrompt(
            question="Pick some",
            choices=(Choice(value="a", label="A"), Choice(value="b", label="B")),
            multi_select=True,
            timeout_seconds=0.05,
        )

        await surface.prompt_choice(prompt)
        content = recorder.sent[0]["attachments"][0]["content"]
        chooser = next(b for b in content["body"] if b.get("type") == "Input.ChoiceSet")
        assert chooser["isMultiSelect"] is True

    async def test_free_text_adds_a_text_input(self) -> None:
        recorder, registry = Recorder(), InteractionRegistry()
        surface = build(recorder, registry)
        prompt = ChoicePrompt(
            question="Anything to add?",
            choices=(Choice(value="no", label="No"),),
            allow_free_text=True,
            timeout_seconds=0.05,
        )

        await surface.prompt_choice(prompt)
        content = recorder.sent[0]["attachments"][0]["content"]
        assert any(b.get("id") == "ccdb_text" for b in content["body"])
