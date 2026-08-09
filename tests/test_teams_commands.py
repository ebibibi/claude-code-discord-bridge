"""Text commands and mention handling — the two things a channel message needs.

Both are about not corrupting what the user said. A router that eats a sentence
because it starts with a slash, or a mention tag left in the prompt, produce the
same class of bug: the session is asked something other than what was typed.
"""

from __future__ import annotations

import pytest

from claude_teams.commands import CommandRouter, parse_command
from claude_teams.mentions import mentions_in, strip_mention_markup, was_mentioned

APP_ID = "11111111-2222-3333-4444-555555555555"


def mention_entity(user_id: str, name: str, text: str = "") -> dict[str, object]:
    return {
        "type": "mention",
        "text": text or f"<at>{name}</at>",
        "mentioned": {"id": user_id, "name": name},
    }


class TestParsing:
    def test_a_bare_command_parses(self) -> None:
        parsed = parse_command("/sessions")
        assert parsed is not None and parsed.name == "sessions" and parsed.args == ""

    def test_arguments_are_kept_verbatim(self) -> None:
        parsed = parse_command("/model  claude-opus-5  ")
        assert parsed is not None and parsed.args == "claude-opus-5"

    def test_the_name_is_case_insensitive(self) -> None:
        parsed = parse_command("/MODEL opus")
        assert parsed is not None and parsed.name == "model"

    def test_ordinary_text_is_not_a_command(self) -> None:
        assert parse_command("please fix the parser") is None
        assert parse_command("") is None

    def test_a_path_is_not_a_command(self) -> None:
        # "/tmp/build.log is missing" is a sentence about a file. A name
        # pattern that allowed slashes would turn it into a command before the
        # registry was even consulted.
        assert parse_command("/tmp/build.log is missing") is None

    def test_a_slash_alone_is_not_a_command(self) -> None:
        assert parse_command("/") is None
        assert parse_command("/ model") is None

    def test_multiline_arguments_survive(self) -> None:
        parsed = parse_command("/note line one\nline two")
        assert parsed is not None and parsed.args == "line one\nline two"


class TestDispatch:
    async def test_a_registered_command_runs(self) -> None:
        router = CommandRouter()
        seen: list[str] = []

        async def handler(command) -> str:  # noqa: ANN001 — ParsedCommand
            seen.append(command.args)
            return "done"

        router.register("model", "Switch the model", handler)
        assert await router.dispatch("/model opus") == "done"
        assert seen == ["opus"]

    async def test_an_unregistered_name_is_not_a_command(self) -> None:
        # The caller must be able to tell "not a command" from "the command
        # produced no output", because the first has to reach the session as
        # ordinary text and the second must not.
        router = CommandRouter()
        assert await router.dispatch("/unknown thing") is None
        assert router.is_command("/unknown thing") is False

    async def test_a_command_with_no_output_still_counts_as_handled(self) -> None:
        router = CommandRouter()

        async def handler(command) -> None:  # noqa: ANN001
            return None

        router.register("stop", "Interrupt the session", handler)
        assert router.is_command("/stop") is True
        assert await router.dispatch("/stop") is None

    async def test_the_activity_reaches_the_handler(self) -> None:
        router = CommandRouter()
        seen: list[object] = []

        async def handler(command) -> None:  # noqa: ANN001
            seen.append(command.activity)

        router.register("stop", "Interrupt the session", handler)
        await router.dispatch("/stop", activity="the-activity")
        assert seen == ["the-activity"]

    def test_registering_the_same_name_twice_is_an_error(self) -> None:
        router = CommandRouter()

        async def handler(command) -> None:  # noqa: ANN001
            return None

        router.register("model", "Switch the model", handler)
        with pytest.raises(ValueError, match="already registered"):
            router.register("/model", "Something else", handler)


class TestTheMenuComesFromTheRegistry:
    def test_the_manifest_menu_lists_what_the_router_answers(self) -> None:
        # Written by hand, the menu drifts: a documented command that does
        # nothing is the failure mode, and nothing catches it.
        router = CommandRouter()

        async def handler(command) -> None:  # noqa: ANN001
            return None

        router.register("model", "Switch the model", handler)
        router.register("sessions", "List running sessions", handler)

        assert [entry["title"] for entry in router.menu()] == ["model", "sessions"]
        assert router.names == ("model", "sessions")


class TestMentionDetection:
    def test_the_bot_recognises_being_addressed(self) -> None:
        raw = {"entities": [mention_entity(f"28:{APP_ID}", "Relay")]}
        assert was_mentioned(raw, APP_ID)

    def test_someone_elses_mention_is_not_ours(self) -> None:
        raw = {"entities": [mention_entity("29:another-user", "Ada")]}
        assert not was_mentioned(raw, APP_ID)

    def test_a_matching_display_name_is_not_enough(self) -> None:
        # Display names are neither unique nor stable. Matching on them would
        # have a bot answer to another app that happens to share its name.
        raw = {"entities": [mention_entity("28:99999999-9999-9999-9999-999999999999", "Relay")]}
        assert not was_mentioned(raw, APP_ID)

    def test_a_message_with_no_entities_is_not_a_mention(self) -> None:
        assert not was_mentioned({}, APP_ID)
        assert not was_mentioned({"entities": "nonsense"}, APP_ID)

    def test_an_empty_app_id_never_matches(self) -> None:
        raw = {"entities": [mention_entity("28:", "Relay")]}
        assert not was_mentioned(raw, "")


class TestMentionList:
    def test_other_people_are_reported(self) -> None:
        raw = {
            "entities": [
                mention_entity(f"28:{APP_ID}", "Relay"),
                mention_entity("29:ada", "Ada"),
            ]
        }
        people = mentions_in(raw, exclude=APP_ID)
        assert [m.display_name for m in people] == ["Ada"]

    def test_without_an_exclusion_the_bot_is_included(self) -> None:
        raw = {"entities": [mention_entity(f"28:{APP_ID}", "Relay")]}
        assert len(mentions_in(raw)) == 1

    def test_malformed_entries_are_skipped_not_fatal(self) -> None:
        raw = {"entities": [{"type": "mention"}, {"type": "mention", "mentioned": {}}, "junk"]}
        assert mentions_in(raw) == ()


class TestMarkupStripping:
    def test_the_tag_is_removed_and_spacing_tidied(self) -> None:
        assert strip_mention_markup("<at>Relay</at>  fix the parser") == "fix the parser"

    def test_a_command_after_a_mention_becomes_parseable(self) -> None:
        # The reason this runs before the router: with the tag in place,
        # "/model opus" is not at the start of the string and no parser sees it.
        cleaned = strip_mention_markup("<at>Relay</at> /model opus")
        assert parse_command(cleaned) is not None

    def test_every_mention_goes_not_only_the_bots(self) -> None:
        # The tags are markup, not content. A session shown "<at>Ada</at> can
        # you review" learns to strip them itself, badly.
        assert strip_mention_markup("<at>Relay</at> ask <at>Ada</at> too") == "ask too"

    def test_a_mention_in_the_middle_leaves_one_space(self) -> None:
        assert strip_mention_markup("tell <at>Ada</at> about it") == "tell about it"

    def test_text_without_mentions_is_untouched(self) -> None:
        assert strip_mention_markup("plain text") == "plain text"

    def test_newlines_survive(self) -> None:
        # Collapsing them would reformat code blocks and lists inside a prompt.
        assert strip_mention_markup("<at>Relay</at> line one\nline two") == "line one\nline two"

    def test_an_empty_message_stays_empty(self) -> None:
        assert strip_mention_markup("") == ""
        assert strip_mention_markup("<at>Relay</at>") == ""


class TestTheManifestAndTheRouterCannotDrift:
    def test_the_generated_menu_matches_a_router_with_the_defaults(self) -> None:
        # The failure this prevents: a command in the Teams menu that nothing
        # answers. Nobody notices until a user picks it.
        from claude_teams.commands import DEFAULT_COMMANDS
        from claude_teams.config import TeamsConfig
        from claude_teams.manifest import build_manifest

        router = CommandRouter()

        async def handler(command) -> None:  # noqa: ANN001
            return None

        for name, description in DEFAULT_COMMANDS:
            router.register(name, description, handler)

        manifest = build_manifest(
            TeamsConfig(
                app_id=APP_ID,
                tenant_id="99999999-8888-7777-6666-555555555555",
                public_host="relay.example.com",
            )
        )
        advertised = manifest["bots"][0]["commandLists"][0]["commands"]
        assert advertised == router.menu()

    def test_a_custom_router_can_replace_the_advertised_menu(self) -> None:
        from claude_teams.config import TeamsConfig
        from claude_teams.manifest import build_manifest

        router = CommandRouter()

        async def handler(command) -> None:  # noqa: ANN001
            return None

        router.register("deploy", "Ship it", handler)
        manifest = build_manifest(
            TeamsConfig(
                app_id=APP_ID,
                tenant_id="99999999-8888-7777-6666-555555555555",
                public_host="relay.example.com",
            ),
            commands=router.menu(),
        )
        advertised = manifest["bots"][0]["commandLists"][0]["commands"]
        assert [c["title"] for c in advertised] == ["deploy"]


class TestActivityConvenience:
    def test_an_activity_exposes_clean_text_and_mentions(self) -> None:
        from claude_teams.activity import parse_activity

        activity = parse_activity(
            {
                "type": "message",
                "serviceUrl": "https://smba.trafficmanager.net/emea/",
                "conversation": {"id": "19:abc@thread.tacv2"},
                "from": {"id": "29:ada", "name": "Ada"},
                "text": "<at>Relay</at> /model opus",
                "entities": [mention_entity(f"28:{APP_ID}", "Relay")],
            }
        )
        assert activity.mentions_bot(APP_ID)
        assert activity.clean_text == "/model opus"
        assert activity.text == "<at>Relay</at> /model opus", "raw text must stay untouched"
        assert activity.mentions(exclude=APP_ID) == ()
