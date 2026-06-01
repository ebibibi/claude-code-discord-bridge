"""Tests for detect_api_provider — maps subprocess env to an API label.

Pure-logic module: aim for full branch coverage with plain dict inputs,
no Discord or subprocess mocking required.
"""

from __future__ import annotations

from claude_code_core.api_provider import detect_api_provider


def test_direct_anthropic_when_no_flags() -> None:
    assert detect_api_provider({}) == "Anthropic API (direct)"


def test_ignores_irrelevant_vars() -> None:
    env = {"PATH": "/usr/bin", "HOME": "/home/x"}
    assert detect_api_provider(env) == "Anthropic API (direct)"


def test_bedrock() -> None:
    assert detect_api_provider({"CLAUDE_CODE_USE_BEDROCK": "1"}) == "AWS Bedrock"


def test_bedrock_with_region() -> None:
    env = {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-east-1"}
    assert detect_api_provider(env) == "AWS Bedrock (us-east-1)"


def test_bedrock_with_default_region_fallback() -> None:
    env = {"CLAUDE_CODE_USE_BEDROCK": "true", "AWS_DEFAULT_REGION": "eu-west-1"}
    assert detect_api_provider(env) == "AWS Bedrock (eu-west-1)"


def test_vertex() -> None:
    assert detect_api_provider({"CLAUDE_CODE_USE_VERTEX": "1"}) == "Google Vertex AI"


def test_vertex_with_region() -> None:
    env = {"CLAUDE_CODE_USE_VERTEX": "1", "CLOUD_ML_REGION": "us-central1"}
    assert detect_api_provider(env) == "Google Vertex AI (us-central1)"


def test_foundry() -> None:
    assert detect_api_provider({"CLAUDE_CODE_USE_FOUNDRY": "1"}) == "Azure AI Foundry"


def test_foundry_with_resource() -> None:
    env = {
        "CLAUDE_CODE_USE_FOUNDRY": "1",
        "ANTHROPIC_FOUNDRY_RESOURCE": "jbs-llm-platform",
    }
    assert detect_api_provider(env) == "Azure AI Foundry (jbs-llm-platform)"


def test_custom_base_url_uses_host() -> None:
    env = {"ANTHROPIC_BASE_URL": "https://apim.example.com/v1/anthropic"}
    assert detect_api_provider(env) == "Custom endpoint (apim.example.com)"


def test_custom_base_url_non_url_falls_back_gracefully() -> None:
    env = {"ANTHROPIC_BASE_URL": "localhost:4000"}
    assert detect_api_provider(env).startswith("Custom endpoint")


def test_bedrock_precedence_over_base_url() -> None:
    env = {"CLAUDE_CODE_USE_BEDROCK": "1", "ANTHROPIC_BASE_URL": "https://x.com"}
    assert detect_api_provider(env) == "AWS Bedrock"


def test_truthy_variations() -> None:
    for val in ("1", "true", "TRUE", "yes", "on", " On "):
        assert detect_api_provider({"CLAUDE_CODE_USE_BEDROCK": val}) == "AWS Bedrock"


def test_falsy_flag_is_direct() -> None:
    for val in ("0", "false", "", "no"):
        assert detect_api_provider({"CLAUDE_CODE_USE_BEDROCK": val}) == ("Anthropic API (direct)")
