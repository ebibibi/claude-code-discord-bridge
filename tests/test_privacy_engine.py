"""Tests for the deterministic replacement engine and its mapping table."""

from __future__ import annotations

import json

import pytest

from claude_code_core.privacy import (
    AnonymizationRules,
    Anonymizer,
    Category,
    MappingStore,
    RulesError,
)

RULES = {
    "terms": [
        {"value": "Contoso Japan", "category": "org"},
        {"value": "Contoso", "category": "org"},
        {"value": "山田太郎", "category": "person"},
    ],
    "patterns": [{"regex": r"srv-[a-z0-9\-]+", "category": "host"}],
}


def make_anonymizer(tmp_path=None, rules_doc=None) -> Anonymizer:
    rules = AnonymizationRules.from_dict(rules_doc or RULES)
    store = MappingStore(tmp_path / "map.json" if tmp_path else None)
    return Anonymizer(rules=rules, store=store)


class TestAnonymize:
    def test_replaces_literal_term(self):
        anon = make_anonymizer()
        result = anon.anonymize("Contoso のADが壊れた")
        assert "Contoso" not in result.text
        assert result.text.startswith("org-001")
        assert result.total_substitutions == 1

    def test_longest_term_wins(self):
        anon = make_anonymizer()
        result = anon.anonymize("Contoso Japan の話")
        # "Contoso Japan" must not be replaced as "org-x Japan".
        assert "Japan" not in result.text
        assert len(result.replacements) == 1

    def test_same_value_always_gets_same_alias(self):
        anon = make_anonymizer()
        first = anon.anonymize("srv-dc01 が落ちた")
        second = anon.anonymize("あとで srv-dc01 を再起動")
        alias = first.replacements[0].alias
        assert alias in second.text

    def test_distinct_values_get_distinct_aliases(self):
        anon = make_anonymizer()
        result = anon.anonymize("srv-dc01 と srv-dc02")
        aliases = {r.alias for r in result.replacements}
        assert len(aliases) == 2

    def test_case_insensitive_match_keeps_one_alias(self):
        anon = make_anonymizer()
        result = anon.anonymize("CONTOSO and contoso")
        assert len(result.replacements) == 1
        assert result.replacements[0].count == 2

    def test_builtin_email_and_ipv4(self):
        anon = make_anonymizer(rules_doc={"terms": [], "builtins": ["email", "ipv4"]})
        result = anon.anonymize("mail ebi@example.co.jp from 192.168.1.10")
        assert "ebi@example.co.jp" not in result.text
        assert "192.168.1.10" not in result.text
        assert "203.0.113.1" in result.text  # documentation range, shape preserved

    def test_no_rules_is_a_noop(self):
        anon = Anonymizer(rules=AnonymizationRules.from_dict({"builtins": []}))
        result = anon.anonymize("Contoso")
        assert result.text == "Contoso"
        assert not result.changed

    def test_empty_text(self):
        anon = make_anonymizer()
        assert anon.anonymize("").text == ""

    def test_summary_is_readable(self):
        anon = make_anonymizer()
        result = anon.anonymize("Contoso Contoso")
        assert "x2" in result.summary()


class TestRestore:
    def test_round_trip(self):
        anon = make_anonymizer()
        original = "Contoso の srv-dc01 を 山田太郎 が見ている"
        result = anon.anonymize(original)
        assert anon.restore(result.text) == original

    def test_restores_case_shifted_alias(self):
        anon = make_anonymizer()
        result = anon.anonymize("srv-dc01")
        alias = result.replacements[0].alias
        assert anon.restore(alias.upper()) == "srv-dc01"

    def test_restore_without_mapping_is_identity(self):
        anon = make_anonymizer()
        assert anon.restore("nothing to do here") == "nothing to do here"

    def test_longer_alias_wins_over_prefix(self):
        anon = make_anonymizer(rules_doc={"terms": [], "builtins": ["ipv4"]})
        # Allocate ten addresses so 203.0.113.1 and 203.0.113.10 coexist.
        text = " ".join(f"10.0.0.{i}" for i in range(1, 11))
        result = anon.anonymize(text)
        assert anon.restore(result.text) == text


class TestMappingStore:
    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "map.json"
        first = MappingStore(path)
        alias = first.alias_for(Category.HOST, "srv-dc01")
        second = MappingStore(path)
        assert second.alias_for(Category.HOST, "srv-dc01") == alias
        assert second.original_for(alias) == "srv-dc01"

    def test_alias_never_collides_across_categories(self, tmp_path):
        store = MappingStore(tmp_path / "map.json")
        a = store.alias_for("org", "Contoso")
        b = store.alias_for("person", "Contoso")
        assert a != b

    def test_file_is_written_atomically_and_is_valid_json(self, tmp_path):
        path = tmp_path / "nested" / "map.json"
        store = MappingStore(path)
        store.alias_for(Category.ORG, "Contoso")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["entries"][0]["original"] == "Contoso"
        assert not list(path.parent.glob("*.tmp"))

    def test_corrupt_table_raises_instead_of_starting_empty(self, tmp_path):
        path = tmp_path / "map.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            MappingStore(path)


class TestRulesLoading:
    def test_bare_string_terms_default_to_term_category(self):
        rules = AnonymizationRules.from_dict({"terms": ["Contoso"], "builtins": []})
        assert rules.matchers[0].category == Category.TERM

    def test_invalid_regex_is_rejected(self):
        with pytest.raises(RulesError):
            AnonymizationRules.from_dict({"patterns": [{"regex": "([a-z"}]})

    def test_empty_matching_regex_is_rejected(self):
        with pytest.raises(RulesError):
            AnonymizationRules.from_dict({"patterns": [{"regex": "x*"}]})

    def test_unknown_builtin_is_rejected(self):
        with pytest.raises(RulesError):
            AnonymizationRules.from_dict({"builtins": ["telepathy"]})

    def test_load_from_file(self, tmp_path):
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(RULES), encoding="utf-8")
        rules = AnonymizationRules.load(path)
        assert not rules.is_empty
        assert rules.source_path == path

    def test_missing_file_raises_rules_error(self, tmp_path):
        with pytest.raises(RulesError):
            AnonymizationRules.load(tmp_path / "nope.json")
