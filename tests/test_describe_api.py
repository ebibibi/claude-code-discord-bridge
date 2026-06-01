"""Tests for SessionBackend.describe_api() across the Claude and Codex runners.

describe_api() must derive its label from the *final* subprocess environment
(``_build_env()``), so CLI env overlays are reflected accurately.
"""

from __future__ import annotations

import os
from pathlib import Path

from claude_code_core.codex_runner import CodexRunner
from claude_code_core.runner import ClaudeRunner

# Env keys that influence provider detection; cleared so the host process
# environment cannot leak into assertions.
_FLAG_KEYS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "ANTHROPIC_FOUNDRY_RESOURCE",
    "ANTHROPIC_BASE_URL",
    "CCDB_CLI_ENV_FILE",
    "OPENAI_BASE_URL",
)


def _clear() -> dict[str, str | None]:
    return {k: os.environ.pop(k, None) for k in _FLAG_KEYS}


def _restore(saved: dict[str, str | None]) -> None:
    for key, value in saved.items():
        if value is not None:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


class TestClaudeDescribeApi:
    def test_direct_by_default(self) -> None:
        saved = _clear()
        try:
            assert ClaudeRunner().describe_api() == "Anthropic API (direct)"
        finally:
            _restore(saved)

    def test_reflects_bedrock_env(self) -> None:
        saved = _clear()
        os.environ["CLAUDE_CODE_USE_BEDROCK"] = "1"
        try:
            assert ClaudeRunner().describe_api() == "AWS Bedrock"
        finally:
            _restore(saved)

    def test_reflects_cli_env_overlay(self, tmp_path: Path) -> None:
        # Real-world Azure Foundry case: provider must reflect overlay vars.
        saved = _clear()
        overlay = tmp_path / "overlay.env"
        overlay.write_text(
            "CLAUDE_CODE_USE_FOUNDRY=1\nANTHROPIC_FOUNDRY_RESOURCE=jbs-llm-platform\n"
        )
        os.environ["CCDB_CLI_ENV_FILE"] = str(overlay)
        try:
            assert ClaudeRunner().describe_api() == "Azure AI Foundry (jbs-llm-platform)"
        finally:
            _restore(saved)


class TestCodexDescribeApi:
    def test_direct_openai_by_default(self) -> None:
        saved = _clear()
        try:
            assert CodexRunner(model="o4-mini").describe_api() == "OpenAI API (direct)"
        finally:
            _restore(saved)

    def test_custom_openai_base_url(self) -> None:
        saved = _clear()
        os.environ["OPENAI_BASE_URL"] = "https://azure-openai.example.com/v1"
        try:
            label = CodexRunner(model="o4-mini").describe_api()
            assert label.startswith("Custom endpoint")
        finally:
            _restore(saved)
