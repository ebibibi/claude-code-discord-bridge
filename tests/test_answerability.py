"""Tests for the answerability judge.

The judge answers a different question from the leak inspector, and the
difference that matters is what happens when it cannot answer at all:

- the inspector guards a *safety* property, so unavailable must mean "block";
- the judge guards a *quality* property, so unavailable must mean "send".

Copying the inspector's fail-closed stance here would break `/ask` for no
safety gain whenever the local model is down. Most of these tests exist to
pin that asymmetry down.
"""

from __future__ import annotations

from claude_code_core.privacy.answerability import (
    AnswerabilityJudge,
    AnswerabilityVerdict,
    parse_verdict,
)


class TestVerdictParsing:
    def test_parses_an_answerable_verdict(self):
        verdict = parse_verdict('{"answerable": true, "reason": "generic Azure question"}')
        assert verdict.answerable is True
        assert verdict.available is True
        assert "Azure" in verdict.reason

    def test_parses_an_unanswerable_verdict(self):
        verdict = parse_verdict('{"answerable": false, "reason": "org-002 の評価が必要"}')
        assert verdict.answerable is False
        assert verdict.blocks is True

    def test_tolerates_a_fenced_reply(self):
        raw = '```json\n{"answerable": false, "reason": "needs the identity"}\n```'
        assert parse_verdict(raw).answerable is False

    def test_unparseable_output_does_not_block(self):
        """A local model babbling is not evidence that the question is bad."""
        verdict = parse_verdict("I think maybe it depends?")
        assert verdict.blocks is False
        assert verdict.available is False

    def test_empty_output_does_not_block(self):
        assert parse_verdict("").blocks is False

    def test_a_missing_answerable_key_does_not_block(self):
        assert parse_verdict('{"reason": "hmm"}').blocks is False


class TestFailOpenAsymmetry:
    """The whole point: an unavailable judge must not stop a good question."""

    def test_an_unavailable_verdict_never_blocks(self):
        verdict = AnswerabilityVerdict(answerable=False, available=False, error="timeout")
        assert verdict.blocks is False

    def test_only_a_verdict_that_ran_may_block(self):
        assert AnswerabilityVerdict(answerable=False, available=True).blocks is True
        assert AnswerabilityVerdict(answerable=True, available=True).blocks is False

    def test_the_default_verdict_is_permissive(self):
        assert AnswerabilityVerdict().blocks is False


class TestJudgeTransport:
    async def test_an_unreachable_endpoint_reports_unavailable(self):
        judge = AnswerabilityJudge(base_url="http://127.0.0.1:1", model="nope", timeout_seconds=0.2)
        verdict = await judge.judge("org-001 について教えて")
        assert verdict.available is False
        assert verdict.blocks is False

    async def test_blank_text_is_not_sent_anywhere(self):
        """No text, no call — and certainly no block."""
        judge = AnswerabilityJudge(base_url="http://127.0.0.1:1", model="nope")
        verdict = await judge.judge("   ")
        assert verdict.blocks is False
        assert verdict.available is True

    async def test_a_verdict_comes_back_from_the_transport(self, monkeypatch):
        async def fake_chat(**kwargs):
            return '{"answerable": false, "reason": "org-002 の実体が必要"}'

        monkeypatch.setattr(
            "claude_code_core.privacy.answerability.chat_json", fake_chat, raising=True
        )
        judge = AnswerabilityJudge(base_url="http://x", model="m")
        verdict = await judge.judge("org-002 の良い点と悪い点")
        assert verdict.blocks is True
        assert verdict.model == "m"

    async def test_the_judge_sees_the_text_it_was_given(self, monkeypatch):
        seen: dict[str, str] = {}

        async def fake_chat(**kwargs):
            seen.update(user=kwargs["user"], system=kwargs["system"])
            return '{"answerable": true, "reason": "fine"}'

        monkeypatch.setattr(
            "claude_code_core.privacy.answerability.chat_json", fake_chat, raising=True
        )
        await AnswerabilityJudge(base_url="http://x", model="m").judge("org-002 とは")
        assert seen["user"] == "org-002 とは"
        # The prompt must tell the model it is looking at placeholders, or it
        # will judge "org-002" to be an unknown company and refuse everything.
        assert "placeholder" in seen["system"].lower()

    async def test_a_transport_failure_is_not_a_block(self, monkeypatch):
        async def boom(**kwargs):
            raise OSError("connection reset")

        monkeypatch.setattr("claude_code_core.privacy.answerability.chat_json", boom, raising=True)
        verdict = await AnswerabilityJudge(base_url="http://x", model="m").judge("org-002")
        assert verdict.available is False
        assert verdict.blocks is False


class TestReasonIsSafeToShow:
    def test_a_long_reason_is_bounded(self):
        verdict = parse_verdict('{"answerable": false, "reason": "' + "あ" * 5000 + '"}')
        assert len(verdict.reason) <= 400
