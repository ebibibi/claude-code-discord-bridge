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


class TestAdopt:
    """Terms the inspector found are replaced by the same deterministic table.

    The model reports; the table still does every substitution. That is what
    keeps an answer restorable — see Key Design Decision 12.
    """

    def _anonymizer(self, store: MappingStore | None = None) -> Anonymizer:
        return Anonymizer(
            rules=AnonymizationRules.from_dict(RULES),
            store=store if store is not None else MappingStore(),
        )

    def test_adopt_replaces_a_term_absent_from_the_rules(self):
        anon = self._anonymizer()
        result = anon.adopt("Fabrikam の件で相談", [("Fabrikam", "org")])
        assert "Fabrikam" not in result.text
        assert result.total_substitutions == 1

    def test_adopted_alias_restores_to_the_real_name(self):
        anon = self._anonymizer()
        result = anon.adopt("Fabrikam の件", [("Fabrikam", "org")])
        assert anon.restore(result.text) == "Fabrikam の件"

    def test_adopted_term_is_replaced_on_the_next_pass_without_the_inspector(self):
        """Learning: once adopted, the term never needs the model again."""
        anon = self._anonymizer()
        anon.adopt("Fabrikam の件", [("Fabrikam", "org")])
        later = anon.anonymize("Fabrikam から再度の問い合わせ")
        assert "Fabrikam" not in later.text
        assert later.changed

    def test_adopted_term_survives_a_new_anonymizer_sharing_the_store(self, tmp_path):
        path = tmp_path / "mapping.json"
        first = self._anonymizer(MappingStore(path))
        first.adopt("Fabrikam の件", [("Fabrikam", "org")])
        first.store.flush()

        second = self._anonymizer(MappingStore(path))
        result = second.anonymize("Fabrikam の続き")
        assert "Fabrikam" not in result.text

    def test_adopt_is_stable_across_calls(self):
        """The same term must get the same alias, or the answer cannot be restored."""
        anon = self._anonymizer()
        first = anon.adopt("Fabrikam", [("Fabrikam", "org")])
        second = anon.adopt("Fabrikam", [("Fabrikam", "org")])
        assert first.text == second.text

    def test_rule_terms_still_win_over_adopted_ones(self):
        anon = self._anonymizer()
        anon.adopt("Contoso", [("Contoso", "person")])  # wrong category on purpose
        result = anon.anonymize("Contoso が落ちた")
        replacement = result.replacements[0]
        assert replacement.category == "org"

    def test_adopt_ignores_terms_absent_from_the_text(self):
        anon = self._anonymizer()
        result = anon.adopt("何も含まれない文", [("Fabrikam", "org")])
        assert result.text == "何も含まれない文"

    def test_adopt_ignores_blank_terms(self):
        anon = self._anonymizer()
        result = anon.adopt("Fabrikam の件", [("", "org"), ("   ", "org")])
        assert result.text == "Fabrikam の件"


class TestMappingOriginals:
    def test_originals_lists_what_was_minted(self):
        store = MappingStore()
        store.alias_for("org", "Fabrikam")
        store.alias_for("person", "鈴木")
        assert set(store.originals()) == {("org", "Fabrikam"), ("person", "鈴木")}

    def test_originals_is_empty_for_a_fresh_store(self):
        assert MappingStore().originals() == []


class TestAdoptGuards:
    """The inspector is a local LLM: its output is untrusted input.

    A one-character "proper noun" would alias a particle and shred the
    sentence; an unbounded list would grow the matcher table without limit.
    """

    def _anonymizer(self) -> Anonymizer:
        return Anonymizer(rules=AnonymizationRules.from_dict(RULES), store=MappingStore())

    def test_single_character_terms_are_ignored(self):
        anon = self._anonymizer()
        result = anon.adopt("これは私の案件です", [("の", "term"), ("私", "person")])
        assert result.text == "これは私の案件です"

    def test_two_character_terms_are_still_adopted(self):
        anon = self._anonymizer()
        result = anon.adopt("NA の案件", [("NA", "org")])
        assert "NA" not in result.text

    def test_the_number_of_adopted_terms_is_capped(self):
        anon = self._anonymizer()
        terms = [(f"Term{i:03d}", "org") for i in range(200)]
        anon.adopt("nothing here", terms)
        assert len(anon.store.originals()) <= 32

    def test_overlong_terms_are_ignored(self):
        """A whole paragraph reported as a name would alias the message itself."""
        anon = self._anonymizer()
        blob = "あ" * 500
        result = anon.adopt(f"{blob} の件", [(blob, "org")])
        assert blob in result.text
