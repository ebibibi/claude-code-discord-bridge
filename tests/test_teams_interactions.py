"""Who is allowed to answer a prompt, and with what.

An Adaptive Card action arrives as an ordinary inbound activity carrying
whatever ``data`` the client sent. Teams authenticates *that a Teams user sent
it*; it does not promise the payload matches a card this process ever posted.
So everything in the payload is untrusted input, and the prompts being answered
here include tool-permission requests.

The tests are written from that angle. Most of them are refusals.
"""

from __future__ import annotations

import asyncio

import pytest

from claude_teams.interactions import InteractionRegistry

CONVERSATION = "19:abc@thread.tacv2"
OTHER_CONVERSATION = "19:someone-elses@thread.tacv2"


def registry() -> InteractionRegistry:
    return InteractionRegistry()


class TestChoiceResolution:
    async def test_an_offered_value_resolves_the_waiter(self) -> None:
        reg = registry()
        pending = reg.register_choice(CONVERSATION, values=("allow", "deny"), multi_select=False)

        assert reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": "allow"})
        assert await asyncio.wait_for(pending.future, 0.1) == ("allow",)

    async def test_a_value_that_was_never_offered_is_refused(self) -> None:
        # The card's data is client-supplied. Without this check a crafted
        # action could return any string as "what the user chose", and a
        # permission request is one of the things being answered.
        reg = registry()
        pending = reg.register_choice(CONVERSATION, values=("deny",), multi_select=False)

        assert not reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": "allow"})
        assert not pending.future.done()

    async def test_a_second_value_is_refused_when_only_one_was_asked_for(self) -> None:
        reg = registry()
        pending = reg.register_choice(CONVERSATION, values=("a", "b"), multi_select=False)

        assert not reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": "a,b"})
        assert not pending.future.done()

    async def test_multi_select_accepts_several_offered_values(self) -> None:
        reg = registry()
        pending = reg.register_choice(CONVERSATION, values=("a", "b", "c"), multi_select=True)

        assert reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": "a,c"})
        assert await asyncio.wait_for(pending.future, 0.1) == ("a", "c")

    async def test_multi_select_still_refuses_an_unoffered_value(self) -> None:
        reg = registry()
        pending = reg.register_choice(CONVERSATION, values=("a", "b"), multi_select=True)

        assert not reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": "a,zzz"})
        assert not pending.future.done()

    async def test_free_text_is_accepted_only_when_the_prompt_allows_it(self) -> None:
        reg = registry()
        closed = reg.register_choice(CONVERSATION, values=("a",), multi_select=False)
        assert not reg.resolve(
            CONVERSATION, {"ccdb_prompt": closed.id, "ccdb_text": "something else"}
        )

        open_ended = reg.register_choice(
            CONVERSATION, values=("a",), multi_select=False, allow_free_text=True
        )
        assert reg.resolve(
            CONVERSATION, {"ccdb_prompt": open_ended.id, "ccdb_text": "something else"}
        )
        assert await asyncio.wait_for(open_ended.future, 0.1) == ("something else",)


class TestConversationBinding:
    async def test_an_action_from_another_conversation_is_refused(self) -> None:
        # The most consequential check here. Without it, someone who learns a
        # prompt id can approve a tool run in a conversation they are not in —
        # and the session would see a perfectly ordinary "the user allowed it".
        reg = registry()
        pending = reg.register_choice(CONVERSATION, values=("allow",), multi_select=False)

        assert not reg.resolve(
            OTHER_CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": "allow"}
        )
        assert not pending.future.done()


class TestReplayAndStaleness:
    async def test_an_unknown_prompt_id_is_refused(self) -> None:
        assert not registry().resolve(CONVERSATION, {"ccdb_prompt": "nope", "ccdb_value": "a"})

    async def test_answering_twice_is_refused_the_second_time(self) -> None:
        reg = registry()
        pending = reg.register_choice(CONVERSATION, values=("a", "b"), multi_select=False)

        assert reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": "a"})
        assert not reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": "b"})
        assert await asyncio.wait_for(pending.future, 0.1) == ("a",)

    async def test_a_cancelled_prompt_can_no_longer_be_answered(self) -> None:
        reg = registry()
        pending = reg.register_choice(CONVERSATION, values=("a",), multi_select=False)
        reg.cancel(pending.id)
        assert not reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": "a"})

    async def test_cancelling_does_not_leave_a_waiter_hanging(self) -> None:
        reg = registry()
        pending = reg.register_choice(CONVERSATION, values=("a",), multi_select=False)
        reg.cancel(pending.id)
        assert await asyncio.wait_for(pending.future, 0.1) is None


class TestMalformedPayloads:
    async def test_a_payload_without_a_prompt_id_is_refused(self) -> None:
        assert not registry().resolve(CONVERSATION, {"ccdb_value": "a"})

    async def test_a_non_dict_payload_is_refused(self) -> None:
        assert not registry().resolve(CONVERSATION, "not a dict")  # type: ignore[arg-type]

    async def test_a_non_string_value_is_refused(self) -> None:
        reg = registry()
        pending = reg.register_choice(CONVERSATION, values=("a",), multi_select=False)
        assert not reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": 42})
        assert not pending.future.done()


class TestForms:
    async def test_only_declared_keys_come_back(self) -> None:
        # An Adaptive Card submit merges every input on the card into the
        # payload — including anything a crafted client adds.
        reg = registry()
        pending = reg.register_form(CONVERSATION, keys=("name", "note"))

        assert reg.resolve(
            CONVERSATION,
            {"ccdb_prompt": pending.id, "name": "Ada", "note": "hi", "is_admin": "true"},
        )
        assert await asyncio.wait_for(pending.future, 0.1) == {"name": "Ada", "note": "hi"}

    async def test_a_missing_optional_field_is_simply_absent(self) -> None:
        reg = registry()
        pending = reg.register_form(CONVERSATION, keys=("name", "note"))

        assert reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "name": "Ada"})
        assert await asyncio.wait_for(pending.future, 0.1) == {"name": "Ada"}

    async def test_values_are_stringified_not_dropped(self) -> None:
        # Input.Toggle and Input.Number send booleans and numbers.
        reg = registry()
        pending = reg.register_form(CONVERSATION, keys=("count", "agree"))

        assert reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "count": 3, "agree": True})
        assert await asyncio.wait_for(pending.future, 0.1) == {"count": "3", "agree": "True"}


class TestStop:
    async def test_a_stop_action_runs_its_callback_once(self) -> None:
        fired: list[int] = []

        async def on_stop() -> None:
            fired.append(1)

        reg = registry()
        pending = reg.register_stop(CONVERSATION, on_stop)

        assert reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id})
        await asyncio.sleep(0)
        assert fired == [1]

        assert not reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id})
        await asyncio.sleep(0)
        assert fired == [1], "a re-pressed Stop must not interrupt the next session"

    async def test_a_stop_from_another_conversation_is_refused(self) -> None:
        fired: list[int] = []

        async def on_stop() -> None:
            fired.append(1)

        reg = registry()
        pending = reg.register_stop(CONVERSATION, on_stop)
        assert not reg.resolve(OTHER_CONVERSATION, {"ccdb_prompt": pending.id})
        await asyncio.sleep(0)
        assert fired == []


class TestIdentifiers:
    async def test_ids_are_unguessable_and_unique(self) -> None:
        reg = registry()
        ids = {
            reg.register_choice(CONVERSATION, values=("a",), multi_select=False).id
            for _ in range(50)
        }
        assert len(ids) == 50
        assert all(len(i) >= 16 for i in ids)


class TestHousekeeping:
    async def test_resolved_prompts_do_not_accumulate(self) -> None:
        # A long-lived process that never forgets a prompt is a slow leak with
        # an obvious cause and no symptom until it matters.
        reg = registry()
        for _ in range(20):
            pending = reg.register_choice(CONVERSATION, values=("a",), multi_select=False)
            reg.resolve(CONVERSATION, {"ccdb_prompt": pending.id, "ccdb_value": "a"})
        assert reg.pending_count == 0

    async def test_a_registry_reports_what_is_still_waiting(self) -> None:
        reg = registry()
        reg.register_choice(CONVERSATION, values=("a",), multi_select=False)
        reg.register_form(CONVERSATION, keys=("k",))
        assert reg.pending_count == 2


class TestConstruction:
    async def test_a_choice_with_no_values_and_no_free_text_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            registry().register_choice(CONVERSATION, values=(), multi_select=False)

    async def test_a_form_with_no_keys_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            registry().register_form(CONVERSATION, keys=())
