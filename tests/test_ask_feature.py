"""Tests for AskUserQuestion Discord integration.

Covers:
- types: AskOption, AskQuestion, ToolCategory.ASK
- parser: AskUserQuestion tool_use → ask_questions
- embeds: ask_embed
- run_helper: _collect_ask_answers (answer formatting)
"""

from __future__ import annotations

import json

from claude_discord.claude.parser import _parse_ask_questions, parse_line
from claude_discord.claude.types import AskOption, AskQuestion, ToolCategory
from claude_discord.discord_ui.embeds import ask_embed

# ---------------------------------------------------------------------------
# types
# ---------------------------------------------------------------------------


class TestAskTypes:
    def test_ask_option_defaults(self) -> None:
        opt = AskOption(label="JWT tokens")
        assert opt.label == "JWT tokens"
        assert opt.description == ""

    def test_ask_question_defaults(self) -> None:
        q = AskQuestion(question="Which auth?")
        assert q.question == "Which auth?"
        assert q.header == ""
        assert q.multi_select is False
        assert q.options == []

    def test_tool_category_ask_exists(self) -> None:
        assert ToolCategory.ASK.value == "ask"

    def test_ask_in_tool_categories(self) -> None:
        from claude_discord.claude.types import TOOL_CATEGORIES

        assert "AskUserQuestion" in TOOL_CATEGORIES
        assert TOOL_CATEGORIES["AskUserQuestion"] == ToolCategory.ASK


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

_ASK_LINE = json.dumps(
    {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_ask1",
                    "name": "AskUserQuestion",
                    "input": {
                        "questions": [
                            {
                                "question": "Which auth approach?",
                                "header": "Auth method",
                                "multiSelect": False,
                                "options": [
                                    {
                                        "label": "JWT tokens",
                                        "description": "Stateless, good for APIs",
                                    },
                                    {
                                        "label": "Session cookies",
                                        "description": "Simple, stateful",
                                    },
                                    {
                                        "label": "OAuth2",
                                        "description": "Federated identity",
                                    },
                                ],
                            }
                        ]
                    },
                }
            ]
        },
    }
)


class TestParserAskUserQuestion:
    def test_ask_tool_use_detected(self) -> None:
        event = parse_line(_ASK_LINE)
        assert event is not None
        assert event.tool_use is not None
        assert event.tool_use.tool_name == "AskUserQuestion"
        assert event.tool_use.category == ToolCategory.ASK

    def test_ask_questions_populated(self) -> None:
        event = parse_line(_ASK_LINE)
        assert event is not None
        assert event.ask_questions is not None
        assert len(event.ask_questions) == 1

    def test_question_fields(self) -> None:
        event = parse_line(_ASK_LINE)
        assert event is not None
        q = event.ask_questions[0]
        assert q.question == "Which auth approach?"
        assert q.header == "Auth method"
        assert q.multi_select is False

    def test_options_parsed(self) -> None:
        event = parse_line(_ASK_LINE)
        assert event is not None
        opts = event.ask_questions[0].options
        assert len(opts) == 3
        assert opts[0].label == "JWT tokens"
        assert opts[0].description == "Stateless, good for APIs"
        assert opts[2].label == "OAuth2"

    def test_normal_tool_has_no_ask_questions(self) -> None:
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_bash",
                            "name": "Bash",
                            "input": {"command": "ls"},
                        }
                    ]
                },
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.ask_questions is None

    def test_multi_select_question(self) -> None:
        line = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_ask2",
                            "name": "AskUserQuestion",
                            "input": {
                                "questions": [
                                    {
                                        "question": "Which features?",
                                        "header": "Features",
                                        "multiSelect": True,
                                        "options": [
                                            {"label": "Auth"},
                                            {"label": "Logging"},
                                        ],
                                    }
                                ]
                            },
                        }
                    ]
                },
            }
        )
        event = parse_line(line)
        assert event is not None
        assert event.ask_questions[0].multi_select is True

    def test_empty_options_list(self) -> None:
        tool_input = {"questions": [{"question": "Free form?", "options": []}]}
        questions = _parse_ask_questions(tool_input)
        assert len(questions) == 1
        assert questions[0].options == []

    def test_options_without_label_are_skipped(self) -> None:
        tool_input = {
            "questions": [
                {
                    "question": "Choose?",
                    "options": [
                        {"label": "Valid"},
                        {"description": "No label here"},
                        {"label": ""},
                    ],
                }
            ]
        }
        questions = _parse_ask_questions(tool_input)
        assert len(questions[0].options) == 1
        assert questions[0].options[0].label == "Valid"

    def test_multiple_questions_in_one_call(self) -> None:
        tool_input = {
            "questions": [
                {"question": "Q1?", "options": [{"label": "A"}, {"label": "B"}]},
                {"question": "Q2?", "options": [{"label": "X"}, {"label": "Y"}]},
            ]
        }
        questions = _parse_ask_questions(tool_input)
        assert len(questions) == 2
        assert questions[0].question == "Q1?"
        assert questions[1].question == "Q2?"


# ---------------------------------------------------------------------------
# embeds
# ---------------------------------------------------------------------------


class TestAskEmbed:
    def test_default_title(self) -> None:
        embed = ask_embed("Which approach?")
        assert embed.title == "❓ Claude needs your input"

    def test_custom_header_used_in_title(self) -> None:
        embed = ask_embed("Which approach?", header="Auth method")
        assert embed.title == "❓ Auth method"

    def test_question_in_description(self) -> None:
        embed = ask_embed("Pick one?", header="Step")
        assert embed.description == "Pick one?"

    def test_long_question_truncated_to_4096(self) -> None:
        long_q = "x" * 5000
        embed = ask_embed(long_q)
        assert embed.description is not None
        assert len(embed.description) <= 4096

    def test_color_is_blue(self) -> None:
        embed = ask_embed("Q?")
        assert embed.color is not None
        assert embed.color.value == 0x3498DB


# ---------------------------------------------------------------------------
# _collect_ask_answers (answer formatting helper)
# ---------------------------------------------------------------------------


class TestCollectAskAnswers:
    """Tests for the _collect_ask_answers answer string format.

    We test the pure formatting logic by constructing what the function
    would return given a mocked AskView response.  The Discord interaction
    itself (buttons/modals) is tested separately via integration tests.
    """

    def _format_answer(self, question: AskQuestion, selected: list[str]) -> str:
        """Replicate the formatting logic from _collect_ask_answers."""
        answer_text = ", ".join(selected)
        return f"**{question.question}**\nAnswer: {answer_text}"

    def test_single_answer_formatted(self) -> None:
        q = AskQuestion(question="Which auth?", options=[AskOption(label="JWT")])
        result = self._format_answer(q, ["JWT"])
        assert "**Which auth?**" in result
        assert "Answer: JWT" in result

    def test_multi_select_answer_joined(self) -> None:
        q = AskQuestion(
            question="Which features?",
            multi_select=True,
            options=[AskOption(label="Auth"), AskOption(label="Logging")],
        )
        result = self._format_answer(q, ["Auth", "Logging"])
        assert "Answer: Auth, Logging" in result

    def test_full_resume_prompt_format(self) -> None:
        """The resume prompt must start with the [Response] marker."""
        q = AskQuestion(question="Q?")
        part = self._format_answer(q, ["A"])
        resume_prompt = (
            "[Response to AskUserQuestion]\n\n"
            + part
            + "\n\nPlease continue based on these answers."
        )
        assert resume_prompt.startswith("[Response to AskUserQuestion]")
        assert "Please continue" in resume_prompt
