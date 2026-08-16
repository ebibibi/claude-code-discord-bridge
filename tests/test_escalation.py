"""Tests for the explicit escalation channel.

The interesting assertions are all about refusal: the value of this module is
that it will not send anything when its isolation is not intact.
"""

from __future__ import annotations

import pytest

from claude_code_core.escalation import (
    CONSULT_DISALLOWED_TOOLS,
    ConsultChannel,
    Escalation,
    IsolationError,
    verify_isolation,
)
from claude_code_core.privacy import (
    AnonymizationRules,
    Anonymizer,
    AuditLog,
    InspectionPolicy,
    InspectionResult,
    MappingStore,
    PrivacyGateway,
    Suspect,
)

RULES = {"terms": [{"value": "Contoso", "category": "org"}], "builtins": []}


def make_gateway(policy=InspectionPolicy.OFF, inspection=None, audit_path=None):
    class _FakeInspector:
        model = "fake"

        async def inspect(self, text: str) -> InspectionResult:
            assert inspection is not None
            return inspection

    return PrivacyGateway(
        anonymizer=Anonymizer(rules=AnonymizationRules.from_dict(RULES), store=MappingStore()),
        inspector=_FakeInspector() if inspection is not None else None,  # type: ignore[arg-type]
        policy=policy,
        audit=AuditLog(audit_path),
    )


class TestIsolationContract:
    def test_a_correct_spawn_has_no_problems(self, tmp_path):
        args = ConsultChannel().build_args("hello")
        assert verify_isolation(args, tmp_path) == []

    def test_missing_setting_sources_is_caught(self, tmp_path):
        args = [a for a in ConsultChannel().build_args("hi") if a != "--setting-sources"]
        problems = verify_isolation(args, tmp_path)
        assert any("setting-sources" in p for p in problems)

    def test_non_empty_setting_sources_is_caught(self, tmp_path):
        args = ConsultChannel().build_args("hi")
        args[args.index("--setting-sources") + 1] = "user"
        assert any("setting-sources" in p for p in verify_isolation(args, tmp_path))

    def test_missing_separator_is_caught(self, tmp_path):
        args = [a for a in ConsultChannel().build_args("hi") if a != "--"]
        assert any("separator" in p for p in verify_isolation(args, tmp_path))

    def test_a_tool_left_enabled_is_caught(self, tmp_path):
        args = [a for a in ConsultChannel().build_args("hi") if a != "Bash"]
        problems = verify_isolation(args, tmp_path)
        assert any("Bash" in p for p in problems)

    def test_a_non_empty_working_directory_is_caught(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("customer notes", encoding="utf-8")
        assert any(
            "not empty" in p for p in verify_isolation(ConsultChannel().build_args("hi"), tmp_path)
        )

    def test_a_missing_working_directory_is_caught(self, tmp_path):
        problems = verify_isolation(ConsultChannel().build_args("hi"), tmp_path / "absent")
        assert any("does not exist" in p for p in problems)

    def test_every_known_tool_is_disallowed(self):
        args = ConsultChannel().build_args("hi")
        listed = args[args.index("--disallowedTools") + 1 : args.index("--")]
        assert set(listed) == set(CONSULT_DISALLOWED_TOOLS)
        # The ones that can reach the filesystem or the network matter most.
        for tool in ("Bash", "Read", "WebFetch", "Task"):
            assert tool in listed

    def test_prompt_is_the_last_argument(self):
        args = ConsultChannel().build_args("the question")
        assert args[-1] == "the question"
        assert args[-2] == "--"


class TestChannelRefusal:
    async def test_broken_isolation_sends_nothing(self, monkeypatch):
        channel = ConsultChannel()
        monkeypatch.setattr(channel, "build_args", lambda prompt: ["claude", "-p", "--", prompt])

        spawned: list[object] = []

        async def _no_spawn(*args: object, **kwargs: object):
            spawned.append(args)

        monkeypatch.setattr("asyncio.create_subprocess_exec", _no_spawn)

        with pytest.raises(IsolationError, match="Nothing was sent"):
            await channel.ask("a question")
        assert spawned == []


class _FakeChannel(ConsultChannel):
    def __init__(self, answer: str) -> None:
        super().__init__()
        self.answer = answer
        self.received: list[str] = []

    async def ask(self, prompt: str) -> str:
        self.received.append(prompt)
        return self.answer


class TestEscalation:
    async def test_question_goes_out_anonymized_and_answer_comes_back_restored(self):
        gateway = make_gateway()
        # Mint the alias first so the fake answer can use it.
        alias = gateway.anonymizer.anonymize("Contoso").replacements[0].alias
        channel = _FakeChannel(f"You should check {alias}'s tenant settings.")
        result = await Escalation(gateway=gateway, channel=channel).consult(
            "Contoso のテナント設定で困っています"
        )

        assert result.allowed
        assert "Contoso" not in channel.received[0]
        assert "Contoso" in result.answer
        assert result.substitutions == 1

    async def test_a_blocked_question_never_reaches_the_channel(self):
        gateway = make_gateway(
            policy=InspectionPolicy.BLOCK,
            inspection=InspectionResult(suspects=(Suspect(value="Fabrikam"),)),
        )
        channel = _FakeChannel("should not happen")
        result = await Escalation(gateway=gateway, channel=channel).consult("Fabrikam の件")

        assert result.blocked
        assert channel.received == []
        assert "Fabrikam" in (result.reason or "")

    async def test_the_audit_records_the_question_and_the_answer(self, tmp_path):
        import json

        path = tmp_path / "audit.jsonl"
        gateway = make_gateway(audit_path=path)
        channel = _FakeChannel("an answer")
        await Escalation(gateway=gateway, channel=channel).consult("Contoso", thread_id=7)

        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        events = [r["event"] for r in records]
        assert events == ["outbound", "consult_answer"]
        assert records[0]["kind"] == "consult"
        assert records[0]["thread_id"] == 7
        assert "Contoso" not in records[0]["text"]
