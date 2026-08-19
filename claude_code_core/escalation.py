"""Explicit escalation: ask a strong external model one self-contained question.

This is the other half of the local-first design. A thread does its work on a
model you control; when it needs research, a second opinion or a plan, exactly
one anonymized question goes out and exactly one answer comes back.

What makes the claim checkable is that the external CLI runs with **no context
of its own**. That is not a documented procedure — it is verified immediately
before every spawn, because a procedure that can be skipped when someone is in
a hurry always eventually is:

1. ``--setting-sources ""`` — no CLAUDE.md, skills or memory.
2. An **empty** temporary directory as cwd — nothing local to read.
3. ``--tools ""`` — every built-in tool disabled, including tools added by a
   future CLI release; no shell to escape the directory with.
4. ``--`` before the prompt — without it the variadic tool list eats the
   prompt and the CLI dies with "Input must be provided...".

Point 1 is not paranoia. Measured with cwd=/home/ebi and every tool already
disabled, changing *only* ``--setting-sources``: with it, the model reported
that a term unique to the project's CLAUDE.md was absent from its context;
without it, present. A naive escalation ships the whole file — customer names
included — no matter how carefully the question was anonymized.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .privacy.gateway import PrivacyGateway

logger = logging.getLogger(__name__)

__all__ = [
    "ConsultChannel",
    "ConsultOutcome",
    "Escalation",
    "IsolationError",
    "verify_isolation",
]


class IsolationError(RuntimeError):
    """Raised when a consult would run without its isolation intact."""


# Secrets and control-plane handles that have no business in a consult.
_STRIPPED_ENV_KEYS = frozenset(
    {
        "CLAUDECODE",
        "DISCORD_BOT_TOKEN",
        "DISCORD_TOKEN",
        "API_SECRET_KEY",
        "CCDB_API_URL",
        "CCDB_API_SECRET",
        "CCDB_CLI_ENV_FILE",
    }
)


def verify_isolation(args: list[str], cwd: str | Path) -> list[str]:
    """Return the isolation guarantees that are NOT in place.

    An empty list means the four properties in the module docstring all hold
    for this exact spawn. Checking the argv we are about to use — rather than
    trusting the code that built it — is what makes this a route and not a
    procedure.
    """
    problems: list[str] = []

    if "--setting-sources" in args:
        index = args.index("--setting-sources")
        if index + 1 >= len(args) or args[index + 1] != "":
            problems.append("--setting-sources is set to something other than empty")
    else:
        problems.append("--setting-sources is missing (CLAUDE.md and skills would be sent)")

    if "--" not in args:
        problems.append("-- separator is missing (the tool list would swallow the prompt)")

    if "--tools" in args:
        index = args.index("--tools")
        if index + 1 >= len(args) or args[index + 1] != "":
            problems.append("built-in tools are not disabled with --tools empty")
    else:
        problems.append("--tools empty is missing")

    if "--allowedTools" in args or "--allowed-tools" in args:
        problems.append("an allowed-tools override is present")

    path = Path(cwd)
    if not path.is_dir():
        problems.append(f"working directory {path} does not exist")
    elif any(path.iterdir()):
        problems.append(f"working directory {path} is not empty")

    return problems


@dataclass(frozen=True)
class ConsultOutcome:
    """The result of one escalation."""

    allowed: bool
    question_sent: str = ""
    answer: str = ""
    reason: str | None = None
    warning: str | None = None
    substitutions: int = 0

    @property
    def blocked(self) -> bool:
        return not self.allowed


@dataclass
class ConsultChannel:
    """Runs one hardened, single-shot, text-only CLI call."""

    command: str = "claude"
    model: str = "sonnet"
    timeout_seconds: int = 300

    def build_args(self, prompt: str) -> list[str]:
        return [
            self.command,
            "-p",
            "--model",
            self.model,
            "--setting-sources",
            "",
            "--tools",
            "",
            "--",
            prompt,
        ]

    async def ask(self, prompt: str) -> str:
        """Ask once and return the plain-text answer."""
        workdir = tempfile.mkdtemp(prefix="ccdb-consult-")
        try:
            args = self.build_args(prompt)
            problems = verify_isolation(args, workdir)
            if problems:
                raise IsolationError(
                    "Refusing to escalate: " + "; ".join(problems) + ". Nothing was sent."
                )
            env = {k: v for k, v in os.environ.items() if k not in _STRIPPED_ENV_KEYS}
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self.timeout_seconds
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                raise
            if process.returncode:
                detail = stderr.decode("utf-8", errors="replace").strip()[:200]
                raise RuntimeError(f"Consult CLI exited with {process.returncode}: {detail}")
            return stdout.decode("utf-8", errors="replace").strip()
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


@dataclass
class Escalation:
    """Anonymize a question, ask an external model, restore the answer."""

    gateway: PrivacyGateway
    channel: ConsultChannel = field(default_factory=ConsultChannel)

    async def consult(self, question: str, **context: object) -> ConsultOutcome:
        """Send one question out, under the gateway's policy."""
        outcome = await self.gateway.guard(question, kind="consult", **context)
        if not outcome.allowed:
            return ConsultOutcome(allowed=False, reason=outcome.reason)

        answer = await self.channel.ask(outcome.text)
        restored = self.gateway.restore(answer)
        self.gateway.audit.record(
            "consult_answer",
            model=self.channel.model,
            answer_chars=len(answer),
            **context,
        )
        return ConsultOutcome(
            allowed=True,
            question_sent=outcome.text,
            answer=restored,
            warning=outcome.warning,
            substitutions=outcome.result.total_substitutions,
        )
