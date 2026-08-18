"""The approval vocabulary must fail closed and round-trip its own values.

These tests exist because the prompt builder and the payload reader are two
halves of one contract: what a prompt offers is what the reader matches on. A
test that only checked the builder would pass while the pair had drifted apart.
"""

from __future__ import annotations

import pytest

from claude_code_core import approvals
from claude_code_core.frontend import Mention
from claude_code_core.types import ElicitationRequest, PermissionRequest


def _permission() -> PermissionRequest:
    return PermissionRequest(
        request_id="req-1",
        tool_name="Bash",
        tool_input={"command": "rm -rf /tmp/x"},
    )


class TestPermission:
    def test_prompt_offers_the_values_the_reader_matches_on(self) -> None:
        prompt = approvals.permission_prompt(_permission())
        values = {choice.value for choice in prompt.choices}

        assert values == {approvals.ALLOW, approvals.DENY}
        assert approvals.permission_result((approvals.ALLOW,)) == {"approved": True}
        assert approvals.permission_result((approvals.DENY,)) == {"approved": False}

    def test_unanswered_denies(self) -> None:
        assert approvals.permission_result(None) == {"approved": False}
        assert approvals.permission_result(()) == {"approved": False}

    def test_unknown_answer_denies(self) -> None:
        """A renamed choice value must not read as approval."""
        assert approvals.permission_result(("yes-please",)) == {"approved": False}

    def test_timeout_default_is_the_denying_choice(self) -> None:
        assert approvals.permission_prompt(_permission()).default_on_timeout == approvals.DENY

    def test_question_carries_tool_name_and_input(self) -> None:
        question = approvals.permission_prompt(_permission()).question

        assert "Bash" in question
        assert "rm -rf /tmp/x" in question

    def test_oversized_tool_input_is_truncated(self) -> None:
        request = PermissionRequest(
            request_id="req-2",
            tool_name="Write",
            tool_input={"content": "x" * 50_000},
        )

        question = approvals.permission_prompt(request).question

        assert len(question) < 10_000
        assert "truncated" in question

    def test_unserializable_input_still_produces_a_question(self) -> None:
        request = PermissionRequest(
            request_id="req-3", tool_name="Weird", tool_input={"obj": object()}
        )

        assert "Weird" in approvals.permission_prompt(request).question

    def test_notify_is_passed_through(self) -> None:
        mention = Mention(external_user_id="42")

        assert approvals.permission_prompt(_permission(), notify=mention).notify == mention


class TestPlan:
    def test_approve_and_cancel_round_trip(self) -> None:
        prompt = approvals.plan_prompt("step 1\nstep 2")

        assert {c.value for c in prompt.choices} == {approvals.APPROVE, approvals.CANCEL}
        assert approvals.plan_result((approvals.APPROVE,)) == {"approved": True}
        assert approvals.plan_result((approvals.CANCEL,)) == {"approved": False}
        assert approvals.plan_result(None) == {"approved": False}

    def test_timeout_default_cancels(self) -> None:
        assert approvals.plan_prompt("anything").default_on_timeout == approvals.CANCEL

    def test_empty_plan_still_builds_an_answerable_prompt(self) -> None:
        """ChoicePrompt rejects an empty question, so a blank plan needs a stand-in."""
        prompt = approvals.plan_prompt("   ")

        assert prompt.question
        assert prompt.choices


class TestElicitationUrl:
    def _request(self) -> ElicitationRequest:
        return ElicitationRequest(
            request_id="e-1",
            server_name="github",
            mode="url-mode",
            message="Authorize the app",
            url="https://example.test/auth",
        )

    def test_done_completes_and_anything_else_does_not(self) -> None:
        prompt = approvals.elicitation_url_prompt(self._request())

        assert {c.value for c in prompt.choices} == {approvals.DONE, approvals.CANCEL}
        assert approvals.elicitation_url_result((approvals.DONE,)) == {"completed": True}
        assert approvals.elicitation_url_result((approvals.CANCEL,)) == {"completed": False}
        assert approvals.elicitation_url_result(None) == {"completed": False}

    def test_header_names_the_server(self) -> None:
        assert "github" in (approvals.elicitation_url_prompt(self._request()).header or "")


class TestElicitationForm:
    def test_schema_becomes_typed_fields(self) -> None:
        request = ElicitationRequest(
            request_id="e-2",
            server_name="jira",
            mode="form-mode",
            schema={
                "properties": {
                    "summary": {"type": "string", "description": "One line"},
                    "points": {"type": "integer"},
                    "urgent": {"type": "boolean"},
                },
                "required": ["summary"],
            },
        )

        fields = approvals.elicitation_form_prompt(request).fields
        by_key = {f.key: f for f in fields}

        assert by_key["summary"].kind == "text"
        assert by_key["summary"].required is True
        assert by_key["points"].kind == "number"
        assert by_key["urgent"].kind == "toggle"
        assert by_key["points"].required is False

    def test_schema_without_properties_still_yields_one_field(self) -> None:
        """A form nobody can fill in is the same as no form at all."""
        request = ElicitationRequest(
            request_id="e-3", server_name="mystery", mode="form-mode", schema={}
        )

        fields = approvals.elicitation_form_prompt(request).fields

        assert len(fields) == 1
        assert fields[0].required is True

    def test_malformed_property_does_not_raise(self) -> None:
        request = ElicitationRequest(
            request_id="e-4",
            server_name="broken",
            mode="form-mode",
            schema={"properties": {"a": "not-a-dict"}},
        )

        fields = approvals.elicitation_form_prompt(request).fields

        assert [f.key for f in fields] == ["a"]

    def test_pathological_schema_is_bounded(self) -> None:
        request = ElicitationRequest(
            request_id="e-5",
            server_name="flood",
            mode="form-mode",
            schema={"properties": {f"k{i}": {"type": "string"} for i in range(200)}},
        )

        assert len(approvals.elicitation_form_prompt(request).fields) == approvals.MAX_FORM_FIELDS

    def test_submitted_values_and_abandonment_are_distinguishable(self) -> None:
        """ "Declined" and "submitted blanks" mean different things to an MCP server."""
        assert approvals.elicitation_form_result({"a": ""}) == {"values": {"a": ""}}
        assert approvals.elicitation_form_result(None) == {"completed": False}


@pytest.mark.parametrize(
    "builder",
    [
        lambda: approvals.permission_prompt(_permission()),
        lambda: approvals.plan_prompt("plan"),
        lambda: approvals.elicitation_url_prompt(
            ElicitationRequest(request_id="x", server_name="s", mode="url-mode")
        ),
    ],
)
def test_every_choice_prompt_fails_closed_on_timeout(builder) -> None:  # noqa: ANN001
    """An unattended session must refuse, never proceed and never hang."""
    prompt = builder()

    assert prompt.timeout_seconds is not None
    assert prompt.default_on_timeout in {approvals.DENY, approvals.CANCEL}
