"""Tests for the inspector, the policy decision, and the backend wrapper."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import pytest

from claude_code_core.privacy import (
    AnonymizationRules,
    Anonymizer,
    AnonymizingBackend,
    AuditLog,
    GatewayScope,
    InspectionPolicy,
    InspectionResult,
    LocalLlmInspector,
    MappingStore,
    PrivacyConfig,
    PrivacyGateway,
    RulesError,
    Suspect,
    get_gateway,
    reset_gateway_cache,
)
from claude_code_core.privacy.inspector import _parse_suspects
from claude_code_core.types import MessageType, StreamEvent, ToolCategory, ToolUseEvent

RULES = {"terms": [{"value": "Contoso", "category": "org"}], "builtins": []}


def make_gateway(policy: str, inspection: InspectionResult | None, audit_path=None):
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


class TestPolicy:
    async def test_clean_text_is_allowed_and_anonymized(self):
        gateway = make_gateway(InspectionPolicy.BLOCK, InspectionResult())
        outcome = await gateway.guard("Contoso が落ちた")
        assert outcome.allowed
        assert "Contoso" not in outcome.text

    async def test_block_policy_stops_on_suspects(self):
        gateway = make_gateway(
            InspectionPolicy.BLOCK, InspectionResult(suspects=(Suspect(value="Fabrikam"),))
        )
        outcome = await gateway.guard("Fabrikam の件")
        assert not outcome.allowed
        assert "Fabrikam" in (outcome.reason or "")

    async def test_warn_policy_sends_but_reports(self):
        gateway = make_gateway(
            InspectionPolicy.WARN, InspectionResult(suspects=(Suspect(value="Fabrikam"),))
        )
        outcome = await gateway.guard("Fabrikam の件")
        assert outcome.allowed
        assert "Fabrikam" in (outcome.warning or "")

    async def test_block_policy_is_fail_closed_when_inspector_is_down(self):
        gateway = make_gateway(
            InspectionPolicy.BLOCK, InspectionResult(available=False, error="connection refused")
        )
        outcome = await gateway.guard("Contoso の件")
        assert not outcome.allowed
        assert "could not be reached" in (outcome.reason or "")

    async def test_warn_policy_sends_when_inspector_is_down(self):
        gateway = make_gateway(
            InspectionPolicy.WARN, InspectionResult(available=False, error="connection refused")
        )
        outcome = await gateway.guard("Contoso の件")
        assert outcome.allowed
        assert "without inspection" in (outcome.warning or "")

    async def test_own_placeholders_are_not_treated_as_leaks(self):
        """Observed with a real local model: it reports our own alias as a leak.

        Under the block policy that false positive stops an already-safe
        message, so the alias check has to be mechanical, not prompt-based.
        """
        gateway = make_gateway(
            InspectionPolicy.BLOCK,
            InspectionResult(suspects=(Suspect(value="org-001", kind="org"),)),
        )
        await gateway.guard("Contoso")  # mints org-001
        outcome = await gateway.guard("Contoso again")
        assert outcome.allowed
        assert outcome.inspection is not None
        assert outcome.inspection.suspects == ()

    async def test_off_policy_skips_inspection_but_still_replaces(self):
        gateway = make_gateway(InspectionPolicy.OFF, None)
        outcome = await gateway.guard("Contoso が落ちた")
        assert outcome.allowed
        assert outcome.inspection is None
        assert "Contoso" not in outcome.text


class TestAudit:
    async def test_audit_records_anonymized_text_not_the_original(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        gateway = make_gateway(InspectionPolicy.OFF, None, audit_path=path)
        await gateway.guard("Contoso が落ちた", thread_id=42)
        record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert record["thread_id"] == 42
        assert record["allowed"] is True
        assert "Contoso" not in record["text"]
        assert record["substitutions"][0]["category"] == "org"

    async def test_audit_can_omit_text(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        gateway = PrivacyGateway(
            anonymizer=Anonymizer(rules=AnonymizationRules.from_dict(RULES), store=MappingStore()),
            inspector=None,
            policy=InspectionPolicy.OFF,
            audit=AuditLog(path, include_text=False),
        )
        await gateway.guard("Contoso")
        record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert "text" not in record

    async def test_disabled_audit_writes_nothing(self, tmp_path):
        gateway = make_gateway(InspectionPolicy.OFF, None, audit_path=None)
        await gateway.guard("Contoso")
        assert not list(tmp_path.iterdir())


class _FakeBackend:
    """Minimal SessionBackend stand-in that echoes what it was given."""

    command = "claude"
    model = "sonnet"

    def __init__(self) -> None:
        self.received: list[str] = []
        self.images = None

    async def run(self, prompt: str, session_id: str | None = None) -> AsyncGenerator:
        self.received.append(prompt)
        yield StreamEvent(
            raw={},
            message_type=MessageType.ASSISTANT,
            text=f"answer about {prompt}",
        )
        yield StreamEvent(raw={}, message_type=MessageType.RESULT, is_complete=True)

    def clone(self, **kwargs: object) -> _FakeBackend:
        return _FakeBackend()


class TestAnonymizingBackend:
    async def test_prompt_is_anonymized_and_answer_restored(self):
        gateway = make_gateway(InspectionPolicy.OFF, None)
        inner = _FakeBackend()
        backend = AnonymizingBackend(inner, gateway)

        events = [event async for event in backend.run("Contoso が落ちた")]

        assert "Contoso" not in inner.received[0]
        assert "Contoso" in (events[0].text or "")

    async def test_blocked_prompt_never_reaches_the_inner_backend(self):
        gateway = make_gateway(
            InspectionPolicy.BLOCK, InspectionResult(suspects=(Suspect(value="Fabrikam"),))
        )
        inner = _FakeBackend()
        backend = AnonymizingBackend(inner, gateway)

        events = [event async for event in backend.run("Fabrikam の件")]

        assert inner.received == []
        assert len(events) == 1
        assert events[0].is_complete
        assert "Fabrikam" in (events[0].error or "")

    async def test_warning_is_emitted_before_the_answer(self):
        gateway = make_gateway(
            InspectionPolicy.WARN, InspectionResult(suspects=(Suspect(value="Fabrikam"),))
        )
        backend = AnonymizingBackend(_FakeBackend(), gateway)

        events = [event async for event in backend.run("Fabrikam の件")]

        assert events[0].message_type is MessageType.SYSTEM
        assert "Fabrikam" in (events[0].text or "")

    async def test_tool_input_is_restored_for_display(self):
        gateway = make_gateway(InspectionPolicy.OFF, None)
        await gateway.guard("Contoso")  # mint the alias
        alias = gateway.anonymizer.store.aliases()[0]

        event = StreamEvent(
            raw={},
            message_type=MessageType.ASSISTANT,
            tool_use=ToolUseEvent(
                tool_id="t1",
                tool_name="Bash",
                tool_input={"command": f"grep {alias} log.txt", "timeout": 5},
                category=ToolCategory.COMMAND,
            ),
        )
        from claude_code_core.privacy.backend import _restore_event

        restored = _restore_event(event, gateway)
        assert restored.tool_use is not None
        assert restored.tool_use.tool_input["command"] == "grep Contoso log.txt"
        assert restored.tool_use.tool_input["timeout"] == 5

    def test_attribute_writes_land_on_the_inner_backend(self):
        gateway = make_gateway(InspectionPolicy.OFF, None)
        inner = _FakeBackend()
        backend = AnonymizingBackend(inner, gateway)

        backend.images = ["x"]  # Cogs mutate the runner in place

        assert inner.images == ["x"]
        assert backend.model == "sonnet"

    def test_clone_stays_wrapped(self):
        gateway = make_gateway(InspectionPolicy.OFF, None)
        clone = AnonymizingBackend(_FakeBackend(), gateway).clone()
        assert isinstance(clone, AnonymizingBackend)


class TestInspectorParsing:
    def test_parses_plain_json(self):
        suspects = _parse_suspects('{"suspects": [{"value": "Fabrikam", "kind": "org"}]}')
        assert suspects[0].value == "Fabrikam"

    def test_parses_fenced_json(self):
        suspects = _parse_suspects('```json\n{"suspects": ["Fabrikam"]}\n```')
        assert suspects[0].value == "Fabrikam"

    def test_non_json_reply_yields_nothing(self):
        assert _parse_suspects("I could not find anything, sorry!") == ()

    def test_empty_suspect_values_are_dropped(self):
        assert _parse_suspects('{"suspects": [{"value": "  "}]}') == ()

    async def test_hallucinated_suspects_are_dropped(self, monkeypatch):
        inspector = LocalLlmInspector(model="fake")
        monkeypatch.setattr(
            inspector,
            "_request",
            lambda text: '{"suspects": ["Fabrikam", "NotInTheText"]}',
        )
        result = await inspector.inspect("Fabrikam had an outage")
        assert [s.value for s in result.suspects] == ["Fabrikam"]

    async def test_unreachable_endpoint_is_reported_not_raised(self):
        inspector = LocalLlmInspector(
            base_url="http://127.0.0.1:1", model="fake", timeout_seconds=1
        )
        result = await inspector.inspect("anything")
        assert not result.available
        assert result.error


class TestConfigAndDiscovery:
    def test_inactive_without_a_rules_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CCDB_ANONYMIZE_RULES", str(tmp_path / "absent.json"))
        reset_gateway_cache()
        assert PrivacyConfig.from_env().active is False
        assert get_gateway() is None

    def test_active_when_the_rules_file_exists(self, tmp_path, monkeypatch):
        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps(RULES), encoding="utf-8")
        monkeypatch.setenv("CCDB_ANONYMIZE_RULES", str(rules))
        monkeypatch.setenv("CCDB_ANONYMIZE_POLICY", "off")
        reset_gateway_cache()
        gateway = get_gateway()
        assert gateway is not None
        assert gateway.policy == InspectionPolicy.OFF
        reset_gateway_cache()

    def test_explicit_disable_wins(self, tmp_path, monkeypatch):
        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps(RULES), encoding="utf-8")
        monkeypatch.setenv("CCDB_ANONYMIZE_RULES", str(rules))
        monkeypatch.setenv("CCDB_ANONYMIZE", "0")
        reset_gateway_cache()
        assert get_gateway() is None
        reset_gateway_cache()

    def test_blank_env_var_does_not_kill_the_default(self, monkeypatch):
        monkeypatch.setenv("CCDB_ANONYMIZE_POLICY", "")
        assert PrivacyConfig.from_env().policy == InspectionPolicy.BLOCK

    def test_unknown_policy_falls_back_to_block(self, monkeypatch):
        monkeypatch.setenv("CCDB_ANONYMIZE_POLICY", "yolo")
        assert PrivacyConfig.from_env().policy == InspectionPolicy.BLOCK

    def test_broken_rules_file_raises_rather_than_disabling(self, tmp_path, monkeypatch):
        rules = tmp_path / "rules.json"
        rules.write_text("{oops", encoding="utf-8")
        monkeypatch.setenv("CCDB_ANONYMIZE_RULES", str(rules))
        reset_gateway_cache()
        with pytest.raises(RulesError):
            get_gateway()
        reset_gateway_cache()

    def test_editing_the_rules_file_refreshes_the_gateway(self, tmp_path, monkeypatch):
        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps(RULES), encoding="utf-8")
        monkeypatch.setenv("CCDB_ANONYMIZE_RULES", str(rules))
        monkeypatch.setenv("CCDB_ANONYMIZE_MAPPING", str(tmp_path / "map.json"))
        monkeypatch.setenv("CCDB_ANONYMIZE_POLICY", "off")
        reset_gateway_cache()
        first = get_gateway()
        assert first is not None
        before = len(first.anonymizer.rules.matchers)

        rules.write_text(
            json.dumps({"terms": ["Contoso", "Fabrikam"], "builtins": []}), encoding="utf-8"
        )
        import os

        os.utime(rules, (0, 0))  # force a different mtime
        second = get_gateway()
        assert second is not None
        assert len(second.anonymizer.rules.matchers) != before
        reset_gateway_cache()


class TestGatewayScope:
    """The gateway sits on the escalation hop by default, not on every message.

    Wrapping every backend once a rules file exists was the original behaviour
    and it is actively wrong in the local-first design: a local thread sends
    nothing to a vendor, so anonymizing it only makes the local model reason
    about aliases — and with the fail-closed default it would stop every
    thread whenever the local inspector is unreachable.
    """

    def test_scope_defaults_to_escalation_only(self, tmp_path, monkeypatch):
        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps(RULES), encoding="utf-8")
        monkeypatch.setenv("CCDB_ANONYMIZE_RULES", str(rules))
        config = PrivacyConfig.from_env()
        assert config.active  # /ask is available
        assert not config.wraps_backends  # ordinary chat is untouched

    def test_scope_all_restores_backend_wrapping(self, tmp_path, monkeypatch):
        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps(RULES), encoding="utf-8")
        monkeypatch.setenv("CCDB_ANONYMIZE_RULES", str(rules))
        monkeypatch.setenv("CCDB_ANONYMIZE_SCOPE", "all")
        assert PrivacyConfig.from_env().wraps_backends

    def test_unknown_scope_falls_back_to_escalation(self, monkeypatch):
        monkeypatch.setenv("CCDB_ANONYMIZE_SCOPE", "everything")
        assert PrivacyConfig.from_env().scope == GatewayScope.ESCALATION

    def test_backend_is_not_wrapped_by_default(self, tmp_path, monkeypatch):
        from claude_code_core.backend import create_backend

        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps(RULES), encoding="utf-8")
        monkeypatch.setenv("CCDB_ANONYMIZE_RULES", str(rules))
        monkeypatch.setenv("CCDB_ANONYMIZE_MAPPING", str(tmp_path / "map.json"))
        reset_gateway_cache()
        runner = create_backend(backend="claude", model="sonnet")
        assert not isinstance(runner, AnonymizingBackend)
        reset_gateway_cache()

    def test_backend_is_wrapped_when_scope_is_all(self, tmp_path, monkeypatch):
        from claude_code_core.backend import create_backend

        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps(RULES), encoding="utf-8")
        monkeypatch.setenv("CCDB_ANONYMIZE_RULES", str(rules))
        monkeypatch.setenv("CCDB_ANONYMIZE_MAPPING", str(tmp_path / "map.json"))
        monkeypatch.setenv("CCDB_ANONYMIZE_SCOPE", "all")
        monkeypatch.setenv("CCDB_ANONYMIZE_POLICY", "off")
        reset_gateway_cache()
        runner = create_backend(backend="claude", model="sonnet")
        assert isinstance(runner, AnonymizingBackend)
        reset_gateway_cache()


class TestAdoptPolicy:
    """`adopt` turns the inspector's report into a replacement instead of a wall.

    The model still only reports; the mapping table still does every
    substitution, so an adopted term stays restorable.
    """

    async def test_reported_term_is_replaced_and_the_message_is_allowed(self):
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(suspects=(Suspect(value="Fabrikam", kind="org"),)),
        )
        outcome = await gateway.guard("Fabrikam の件で相談")
        assert outcome.allowed
        assert "Fabrikam" not in outcome.text
        assert outcome.adopted

    async def test_rule_terms_are_still_replaced_alongside_adopted_ones(self):
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(suspects=(Suspect(value="Fabrikam", kind="org"),)),
        )
        outcome = await gateway.guard("Contoso と Fabrikam の件")
        assert "Contoso" not in outcome.text
        assert "Fabrikam" not in outcome.text

    async def test_adopted_alias_restores_to_the_real_name(self):
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(suspects=(Suspect(value="Fabrikam", kind="org"),)),
        )
        outcome = await gateway.guard("Fabrikam の件")
        assert gateway.restore(outcome.text) == "Fabrikam の件"

    async def test_unreachable_inspector_still_blocks(self):
        """Adopting is about missed terms, not about lowering the bar."""
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(available=False, error="connection refused", model="fake"),
        )
        outcome = await gateway.guard("Contoso が落ちた")
        assert not outcome.allowed
        assert outcome.reason is not None

    async def test_clean_text_is_untouched(self):
        gateway = make_gateway(InspectionPolicy.ADOPT, InspectionResult())
        outcome = await gateway.guard("Contoso が落ちた")
        assert outcome.allowed
        assert not outcome.adopted

    async def test_adoption_is_recorded_in_the_audit_log(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(suspects=(Suspect(value="Fabrikam", kind="org"),)),
            audit_path=path,
        )
        await gateway.guard("Fabrikam の件")
        record = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert record["adopted"]
        assert record["allowed"] is True

    async def test_the_real_name_never_appears_in_the_outcome_metadata(self):
        """`adopted` is shown in Discord, so it carries aliases, not real names."""
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(suspects=(Suspect(value="Fabrikam", kind="org"),)),
        )
        outcome = await gateway.guard("Fabrikam の件")
        assert "Fabrikam" not in " ".join(outcome.adopted)
        assert "Fabrikam" not in (outcome.warning or "")

    async def test_adopted_term_needs_no_inspector_on_the_next_pass(self):
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(suspects=(Suspect(value="Fabrikam", kind="org"),)),
        )
        await gateway.guard("Fabrikam の件")
        gateway.inspector = None  # the model is gone; the table remembers
        gateway.policy = InspectionPolicy.OFF
        outcome = await gateway.guard("Fabrikam から再度の連絡")
        assert "Fabrikam" not in outcome.text


class TestAdoptConfig:
    def test_adopt_is_a_valid_policy(self, monkeypatch, tmp_path):
        rules = tmp_path / "rules.json"
        rules.write_text(json.dumps(RULES), encoding="utf-8")
        monkeypatch.setenv("CCDB_ANONYMIZE_RULES", str(rules))
        monkeypatch.setenv("CCDB_ANONYMIZE_POLICY", "adopt")
        assert PrivacyConfig.from_env().policy == InspectionPolicy.ADOPT


class TestAdoptFallsBackToBlocking:
    """A term the engine refuses to adopt must not be silently declared safe.

    Adoption has bounds (length, count). Anything outside them is still an
    unreplaced proper noun, so the message has to stop like it would under
    `block` — clearing the report because we *tried* would send the real name.
    """

    async def test_a_term_too_short_to_adopt_still_blocks(self):
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(suspects=(Suspect(value="の", kind="term"),)),
        )
        outcome = await gateway.guard("これは私の案件です")
        assert not outcome.allowed
        assert not outcome.adopted

    async def test_a_term_too_long_to_adopt_still_blocks(self):
        blob = "あ" * 500
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(suspects=(Suspect(value=blob, kind="org"),)),
        )
        outcome = await gateway.guard(f"{blob} の件")
        assert not outcome.allowed

    async def test_adoptable_and_unadoptable_together_still_block(self):
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(
                suspects=(Suspect(value="Fabrikam", kind="org"), Suspect(value="の", kind="term"))
            ),
        )
        outcome = await gateway.guard("Fabrikam の件")
        assert not outcome.allowed


class TestAdoptedAliasesAreReal:
    async def test_reported_aliases_are_the_ones_actually_substituted(self):
        """`adopted` must name the aliases in the sent text, not a second set.

        Resolving the alias a second time with the raw inspector category mints
        a parallel entry, so the surfaced alias differs from the substituted one
        and the mapping table grows two rows per term.
        """
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(suspects=(Suspect(value="Fabrikam", kind="organization_name"),)),
        )
        outcome = await gateway.guard("Fabrikam の件")
        assert outcome.adopted
        for alias in outcome.adopted:
            assert alias in outcome.text

    async def test_one_term_makes_one_mapping_entry(self):
        gateway = make_gateway(
            InspectionPolicy.ADOPT,
            InspectionResult(suspects=(Suspect(value="Fabrikam", kind="organization_name"),)),
        )
        await gateway.guard("Fabrikam の件")
        assert len(gateway.anonymizer.store.originals()) == 1
