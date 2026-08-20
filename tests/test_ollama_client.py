"""Tests for the Ollama native-API client.

The interesting behaviour is not "does it parse JSON" but the two places where a
wrong answer is worse than an error: deriving the management origin from the
``/v1`` URL the operator configured, and reporting whether a model can call
tools. A model listed as usable that cannot call tools produces a Codex session
that describes work instead of doing it, which is the exact failure this client
exists to make visible.
"""

from __future__ import annotations

import pytest

from claude_code_core import ollama_client
from claude_code_core.ollama_client import (
    ModelDetail,
    OllamaError,
    OllamaModel,
    RunningModel,
    _extract_max_context,
    delete_model,
    list_models,
    ollama_api_url,
    pull_model,
    running_models,
    server_version,
    show_model,
    validate_ollama_model_name,
)


@pytest.fixture
def capture_requests(monkeypatch):
    """Replace the blocking transport, recording calls and replaying answers."""
    calls: list[dict] = []
    replies: dict[str, object] = {}

    def fake(url, *, method="GET", payload=None, timeout_seconds=0.0):
        calls.append({"url": url, "method": method, "payload": payload, "timeout": timeout_seconds})
        for suffix, reply in replies.items():
            if url.endswith(suffix):
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise AssertionError(f"no stubbed reply for {url}")

    monkeypatch.setattr(ollama_client, "_request_sync", fake)
    return calls, replies


class TestApiUrlDerivation:
    def test_replaces_the_terminal_v1(self):
        assert (
            ollama_api_url("http://192.168.1.3:11434/v1", "/api/tags")
            == "http://192.168.1.3:11434/api/tags"
        )

    def test_accepts_a_base_url_without_v1(self):
        assert ollama_api_url("http://host:11434", "/api/ps") == "http://host:11434/api/ps"

    def test_preserves_a_reverse_proxy_prefix(self):
        # A gateway that mounts Ollama under a path must keep that path, or
        # every management call 404s while chat keeps working — the most
        # confusing possible failure.
        assert (
            ollama_api_url("https://gw.example/ollama/v1", "/api/tags")
            == "https://gw.example/ollama/api/tags"
        )

    def test_tolerates_a_trailing_slash(self):
        assert ollama_api_url("http://host:11434/v1/", "/api/tags") == "http://host:11434/api/tags"

    @pytest.mark.parametrize(
        "bad",
        [
            "ftp://host/v1",
            "not a url",
            "http://user:pw@host:11434/v1",
            "",
        ],
    )
    def test_rejects_unusable_base_urls(self, bad):
        with pytest.raises(ValueError):
            ollama_api_url(bad, "/api/tags")


class TestModelNameValidation:
    @pytest.mark.parametrize(
        "name",
        ["gpt-oss:120b", "qwen3.6:35b-a3b-mtp-q4_K_M", "library/model", "glm-4.7-flash"],
    )
    def test_accepts_real_names(self, name):
        assert validate_ollama_model_name(name) == name

    @pytest.mark.parametrize(
        "name",
        ["", "   ", "model name", "http://evil/model", "model;rm -rf /", "a" * 256],
    )
    def test_rejects_anything_else(self, name):
        with pytest.raises(ValueError):
            validate_ollama_model_name(name)

    def test_strips_surrounding_whitespace(self):
        assert validate_ollama_model_name("  gpt-oss:120b \n") == "gpt-oss:120b"


class TestListModels:
    @pytest.mark.asyncio
    async def test_parses_and_sorts_largest_first(self, capture_requests):
        calls, replies = capture_requests
        replies["/api/tags"] = {
            "models": [
                {
                    "name": "small:1b",
                    "size": 1_000_000_000,
                    "details": {"parameter_size": "1B", "quantization_level": "Q4"},
                    "capabilities": ["completion"],
                },
                {
                    "name": "big:120b",
                    "size": 65_000_000_000,
                    "details": {"parameter_size": "116.8B", "quantization_level": "MXFP4"},
                    "capabilities": ["completion", "tools", "thinking"],
                },
            ]
        }
        models = await list_models("http://host:11434/v1")
        assert [m.name for m in models] == ["big:120b", "small:1b"]
        assert models[0].supports_tools is True
        assert models[1].supports_tools is False
        assert models[0].size_gb == pytest.approx(65.0)
        assert calls[0]["url"] == "http://host:11434/api/tags"

    @pytest.mark.asyncio
    async def test_empty_server_is_not_an_error(self, capture_requests):
        _, replies = capture_requests
        replies["/api/tags"] = {"models": []}
        assert await list_models("http://host:11434/v1") == []

    @pytest.mark.asyncio
    async def test_surfaces_transport_failures(self, capture_requests):
        _, replies = capture_requests
        replies["/api/tags"] = OllamaError("Could not reach the Ollama server: refused")
        with pytest.raises(OllamaError):
            await list_models("http://host:11434/v1")


class TestRunningModels:
    @pytest.mark.asyncio
    async def test_reports_gpu_placement(self, capture_requests):
        _, replies = capture_requests
        replies["/api/ps"] = {
            "models": [
                {
                    "name": "spilled:70b",
                    "size": 40_000_000_000,
                    "size_vram": 20_000_000_000,
                    "context_length": 8192,
                }
            ]
        }
        (entry,) = await running_models("http://host:11434/v1")
        # Half in system RAM: the number that explains "why is it so slow".
        assert entry.fully_on_gpu is False
        assert entry.gpu_percent == 50

    @pytest.mark.asyncio
    async def test_fully_resident_model_reports_100_percent(self, capture_requests):
        _, replies = capture_requests
        replies["/api/ps"] = {
            "models": [{"name": "m", "size": 1_000, "size_vram": 1_000, "context_length": 4096}]
        }
        (entry,) = await running_models("http://host:11434/v1")
        assert entry.fully_on_gpu is True
        assert entry.gpu_percent == 100

    @pytest.mark.asyncio
    async def test_nothing_loaded_is_an_empty_list(self, capture_requests):
        _, replies = capture_requests
        replies["/api/ps"] = {"models": []}
        assert await running_models("http://host:11434/v1") == []

    def test_zero_size_does_not_divide_by_zero(self):
        entry = RunningModel(name="m", size_bytes=0, size_vram_bytes=0)
        assert entry.gpu_percent == 0
        assert entry.fully_on_gpu is False


class TestShowModel:
    @pytest.mark.asyncio
    async def test_extracts_capabilities_and_context(self, capture_requests):
        calls, replies = capture_requests
        replies["/api/show"] = {
            "capabilities": ["completion", "tools", "thinking"],
            "details": {"parameter_size": "116.8B", "quantization_level": "MXFP4"},
            "model_info": {
                "gptoss.block_count": 36,
                "gptoss.context_length": 131072,
                "gptoss.rope.scaling.original_context_length": 4096,
            },
            "parameters": "temperature 1",
        }
        detail = await show_model("http://host:11434/v1", "gpt-oss:120b")
        assert detail.supports_tools is True
        # The RoPE pre-scaling window must not win — reporting 4,096 would send
        # an operator chasing a context problem that does not exist.
        assert detail.max_context_length == 131072
        assert calls[0]["payload"] == {"model": "gpt-oss:120b"}

    @pytest.mark.asyncio
    async def test_validates_the_name_before_calling(self, capture_requests):
        calls, _ = capture_requests
        with pytest.raises(ValueError):
            await show_model("http://host:11434/v1", "bad name")
        assert calls == []

    def test_context_extraction_ignores_unrelated_keys(self):
        assert _extract_max_context({"general.file_type": 2, "tokenizer.ggml.model": "gpt2"}) == 0

    def test_context_extraction_survives_a_non_numeric_value(self):
        assert (
            _extract_max_context({"x.context_length": "unknown", "y.context_length": 8192}) == 8192
        )


class TestMutations:
    @pytest.mark.asyncio
    async def test_delete_uses_the_delete_verb(self, capture_requests):
        calls, replies = capture_requests
        replies["/api/delete"] = {}
        await delete_model("http://host:11434/v1", "old:7b")
        assert calls[0]["method"] == "DELETE"
        assert calls[0]["payload"] == {"model": "old:7b"}

    @pytest.mark.asyncio
    async def test_pull_requires_a_success_status(self, capture_requests):
        _, replies = capture_requests
        replies["/api/pull"] = {"status": "pulling manifest"}
        # A non-success terminal status must raise: reporting "installed" for a
        # model that is not there fails later, inside a thread, with a worse error.
        with pytest.raises(OllamaError):
            await pull_model("http://host:11434/v1", "gpt-oss:120b")

    @pytest.mark.asyncio
    async def test_pull_accepts_success(self, capture_requests):
        calls, replies = capture_requests
        replies["/api/pull"] = {"status": "success"}
        await pull_model("http://host:11434/v1", "gpt-oss:120b")
        assert calls[0]["payload"] == {"model": "gpt-oss:120b", "stream": False}

    @pytest.mark.asyncio
    async def test_version(self, capture_requests):
        _, replies = capture_requests
        replies["/api/version"] = {"version": "0.32.9"}
        assert await server_version("http://host:11434/v1") == "0.32.9"


class TestRecords:
    def test_model_detail_reports_missing_tool_support(self):
        assert ModelDetail(name="m", capabilities=("completion",)).supports_tools is False

    def test_model_payload_falls_back_to_the_model_key(self):
        parsed = OllamaModel.from_payload({"model": "x:1b", "size": 10})
        assert parsed.name == "x:1b"
