"""Claude/Codex OS-level sandbox parity.

Background: Codex's CLI bundles its own bwrap-style sandbox helper that,
unless told ``--sandbox danger-full-access``, creates an isolated network
namespace to enforce its default fs/network restriction. On hosts that
restrict unprivileged namespace creation (e.g. Ubuntu's
``apparmor_restrict_unprivileged_userns``), that namespace setup fails
outright, surfacing as::

    bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted

for every command the Codex-backed session tries to run — confirmed by
reproducing it directly against codex-cli 0.145.0 on the ccdb host.

Claude Code has no such inner OS sandbox: it always relies solely on ccdb's
own outer boundary (systemd unit sandboxing + per-session worktree). These
tests lock in that both backends now defer to the *same* shared outer
boundary — Codex's redundant, host-incompatible inner layer must never come
back as the default.
"""

from __future__ import annotations

import pytest

from claude_code_core.backend import SessionBackend
from claude_code_core.codex_runner import CodexRunner
from claude_code_core.runner import ClaudeRunner


class TestSandboxParity:
    def test_both_backends_satisfy_protocol_with_describe_sandbox(self) -> None:
        assert isinstance(ClaudeRunner(), SessionBackend)
        assert isinstance(CodexRunner(), SessionBackend)
        assert hasattr(ClaudeRunner(), "describe_sandbox")
        assert hasattr(CodexRunner(), "describe_sandbox")

    def test_claude_never_adds_an_os_level_sandbox(self) -> None:
        """Claude has no inner sandbox of its own, regardless of permission_mode —
        the boundary is entirely ccdb's, matching Codex's `danger-full-access`."""
        for mode in ("acceptEdits", "full", "plan", "auto", "bypassPermissions"):
            for skip in (True, False):
                runner = ClaudeRunner(permission_mode=mode, dangerously_skip_permissions=skip)
                assert "none" in runner.describe_sandbox()
                args = runner._build_args("hi", session_id=None)
                assert not any(a.startswith("--sandbox") for a in args)

    @pytest.mark.parametrize(
        "permission_mode", ["acceptEdits", "full", "none", "default", "auto", "plan"]
    )
    def test_codex_defers_to_full_access_regardless_of_permission_mode(
        self, permission_mode: str
    ) -> None:
        """Codex must never fall back to its own restricted default (read-only /
        workspace-write) — that is exactly the path that triggers the bwrap
        namespace failure. `permission_mode` has no OS-level meaning for Codex
        (codex exec has no approval loop to gate)."""
        runner = CodexRunner(permission_mode=permission_mode, dangerously_skip_permissions=False)
        args = runner._build_args("hi", session_id=None)

        assert args[args.index("--sandbox") + 1] == "danger-full-access"
        assert "read-only" not in args
        assert "workspace-write" not in args

    def test_codex_describe_sandbox_matches_build_args(self) -> None:
        """describe_sandbox() must be a single source of truth — whatever it
        reports is exactly what `_build_args` actually passes to the CLI."""
        for skip in (True, False):
            runner = CodexRunner(dangerously_skip_permissions=skip)
            args = runner._build_args("hi", session_id=None)
            description = runner.describe_sandbox()
            for token in description.split():
                assert token in args, f"describe_sandbox() token {token!r} not in real args"

    def test_codex_never_emits_the_broken_ask_for_approval_flag(self) -> None:
        """`codex exec` rejects `--ask-for-approval` outright (global/interactive-only
        flag on codex-cli >= ~0.13x) — regression guard against reintroducing it."""
        for mode in ("acceptEdits", "full", "none", "default", "auto", "plan"):
            for skip in (True, False):
                runner = CodexRunner(permission_mode=mode, dangerously_skip_permissions=skip)
                args = runner._build_args("hi", session_id=None)
                assert "--ask-for-approval" not in args
                assert "-a" not in args
