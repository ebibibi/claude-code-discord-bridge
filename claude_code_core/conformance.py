"""The contract every :class:`~claude_code_core.frontend.ConversationSurface` owes.

Why this ships in the package rather than living in ``tests/``
--------------------------------------------------------------
A protocol only prevents divergence if there is something that *checks*. Type
hints say a surface has ``prompt_choice``; nothing in the type system says the
value it returns has to be one of the choices that were offered, or that
``deliver_files`` on a surface allowing one file per message must still deliver
all five. Those are the rules a second frontend silently breaks, and "Teams is
missing something" is exactly how it would surface — months later, to a user.

So the checks are importable. Anyone writing a frontend — the Teams one here,
a Slack one later, or one built by somebody deploying this — runs
:func:`check_surface` against their implementation and gets the same verdict
this repository's own Discord implementation gets.

Deliberately framework-free: plain async functions returning a report, not
pytest fixtures. A consumer should not have to adopt our test runner to find
out whether their surface is correct.

What is checked, and what is not
--------------------------------
These are *semantic* obligations that hold regardless of platform:

* the surface reports capabilities consistent with its own behaviour
* text comes back out the way it went in, split only when it must be
* a choice prompt returns something that was actually offered
* files are all delivered even when the surface batches them
* handles are idempotent — completing twice is not an error

Appearance is not checked. Discord posting an embed per tool call and Teams
folding the same information into one updating card are both correct; that
freedom is the entire point of naming intents rather than widgets.

One obligation deliberately lives outside this contract
-------------------------------------------------------
``ChoicePrompt.default_on_timeout`` exists so an unattended tool-permission
request denies rather than hangs, and getting that wrong is the most dangerous
failure in the protocol. It is nevertheless *not* checked here, because it
cannot be: from outside, "the user chose allow" and "the surface invented
allow when nobody answered" are the same return value, and the contract has no
way to force nobody to answer. Each frontend proves it in its own tests, where
the interaction can actually be withheld — see
``tests/test_discord_surface.py::TestChoicePrompt``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .frontend import (
    ActivitySpec,
    Choice,
    ChoicePrompt,
    ConversationSurface,
    FormField,
    FormPrompt,
    Notice,
    NoticeLevel,
    OutboundFile,
    SessionFrontend,
    StatusKind,
)

__all__ = ["ConformanceReport", "check_frontend", "check_surface"]


@dataclass
class ConformanceReport:
    """Outcome of :func:`check_surface`."""

    passed: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        if self.ok:
            return f"all {len(self.passed)} conformance checks passed"
        lines = [f"{len(self.failures)} of {len(self.passed) + len(self.failures)} checks failed:"]
        lines.extend(f"  - {f}" for f in self.failures)
        return "\n".join(lines)


SurfaceFactory = Callable[[], Awaitable[ConversationSurface]]


async def check_surface(make_surface: SurfaceFactory) -> ConformanceReport:
    """Run every contract check against surfaces produced by *make_surface*.

    A fresh surface is requested per check so one check's leftovers cannot
    make the next one pass or fail spuriously.

    Args:
        make_surface: Async callable returning a ready-to-use surface. It is
            called once per check.

    Returns:
        A report. ``report.ok`` is the verdict; ``report.summary()`` explains.
    """
    report = ConformanceReport()
    for name, check in _CHECKS:
        try:
            surface = await make_surface()
            await check(surface)
        except AssertionError as exc:
            report.failures.append(f"{name}: {exc}")
        except Exception as exc:  # noqa: BLE001 — an unexpected raise is also a failure
            report.failures.append(f"{name}: raised {type(exc).__name__}: {exc}")
        else:
            report.passed.append(name)
    return report


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


async def _check_identity(s: ConversationSurface) -> None:
    assert isinstance(s.thread_key, int), "thread_key must be an int — it is the ledger's key"
    assert s.thread_key > 0, "thread_key must be positive"
    assert s.external_id, "external_id must not be empty"
    assert s.frontend, "frontend must name the platform"


async def _check_capabilities_are_sane(s: ConversationSurface) -> None:
    caps = s.capabilities
    assert caps.max_message_chars > 0, "max_message_chars must be positive"
    assert caps.min_update_interval > 0, "min_update_interval must be positive"
    assert caps.max_files_per_message >= 1, "a surface must accept at least one file per message"


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


async def _check_send_text_roundtrip(s: ConversationSurface) -> None:
    await s.send_text("hello")
    sent = _sent_text(s)
    assert sent, "send_text produced nothing"
    assert "hello" in "".join(sent), "the text sent did not reach the surface"


async def _check_long_text_is_split_to_fit(s: ConversationSurface) -> None:
    limit = s.capabilities.max_message_chars
    await s.send_text("x" * (limit * 3))
    for part in _sent_text(s):
        assert len(part) <= limit, (
            f"a message of {len(part)} chars exceeds the declared limit of {limit}"
        )


async def _check_empty_text_sends_nothing(s: ConversationSurface) -> None:
    await s.send_text("")
    assert not _sent_text(s), "an empty message must not be posted"


async def _check_stream_accumulates(s: ConversationSurface) -> None:
    stream = s.open_stream()
    assert not stream.has_content, "a fresh stream must report no content"
    await stream.append("Hello, ")
    assert stream.has_content, "has_content must be True once text has been appended"
    await stream.append("world")
    final = await stream.finalize()
    assert "Hello, world" in final, f"stream lost text: {final!r}"


async def _check_stream_finalize_is_idempotent(s: ConversationSurface) -> None:
    stream = s.open_stream()
    await stream.append("done")
    first = await stream.finalize()
    second = await stream.finalize()
    assert first == second, "finalizing twice must not change or duplicate the result"


# ---------------------------------------------------------------------------
# Notices and activities
# ---------------------------------------------------------------------------


async def _check_notice_is_accepted(s: ConversationSurface) -> None:
    for level in NoticeLevel:
        await s.send_notice(Notice(level=level, title="t", body="b"))


async def _check_activity_lifecycle(s: ConversationSurface) -> None:
    handle = await s.open_activity(ActivitySpec(kind="tool", title="Read", detail="a.py"))
    await handle.update("still reading")
    await handle.complete("42 lines")
    # Completing twice must be harmless: a session that errors after finishing
    # a tool would otherwise take the surface down with it.
    await handle.complete("42 lines")


async def _check_activity_cancel(s: ConversationSurface) -> None:
    handle = await s.open_activity(ActivitySpec(kind="tool", title="Bash"))
    await handle.cancel()
    await handle.cancel()


async def _check_status_transitions(s: ConversationSurface) -> None:
    for status in StatusKind:
        await s.set_status(status)
    await s.clear_status()
    await s.clear_status()


# ---------------------------------------------------------------------------
# Interaction
# ---------------------------------------------------------------------------


# Every prompt in these checks carries a timeout. Without one, a surface that
# waits for a real human — which is correct behaviour — would hang the checker
# forever, and the contract would be untestable rather than unsatisfied.
_PROMPT_TIMEOUT = 0.05


async def _check_choice_returns_an_offered_value(s: ConversationSurface) -> None:
    offered = (Choice(value="allow", label="Allow"), Choice(value="deny", label="Deny"))
    answer = await s.prompt_choice(
        ChoicePrompt(question="Run it?", choices=offered, timeout_seconds=_PROMPT_TIMEOUT)
    )
    if answer is None:
        return  # "unanswered" is a legitimate outcome
    values = {c.value for c in offered}
    assert set(answer) <= values, (
        f"prompt_choice returned {answer!r}, which is not among the offered {sorted(values)}"
    )


async def _check_single_select_returns_at_most_one(s: ConversationSurface) -> None:
    answer = await s.prompt_choice(
        ChoicePrompt(
            question="Pick one",
            choices=(Choice(value="a", label="A"), Choice(value="b", label="B")),
            multi_select=False,
            timeout_seconds=_PROMPT_TIMEOUT,
        )
    )
    if answer is not None:
        assert len(answer) <= 1, "multi_select=False must not return more than one value"


async def _check_form_answers_only_known_keys(s: ConversationSurface) -> None:
    fields = (
        FormField(key="name", label="Name", kind="text"),
        FormField(key="note", label="Note", kind="multiline"),
    )
    answer = await s.prompt_form(
        FormPrompt(title="Details", fields=fields, timeout_seconds=_PROMPT_TIMEOUT)
    )
    if answer is None:
        return
    known = {f.key for f in fields}
    unknown = set(answer) - known
    assert not unknown, f"prompt_form returned keys that were never asked for: {sorted(unknown)}"


async def _check_interrupt_handle(s: ConversationSurface) -> None:
    stopped: list[bool] = []

    async def on_stop() -> None:
        stopped.append(True)

    handle = await s.offer_interrupt(on_stop)
    await handle.bump()
    await handle.disable()
    # Disabling twice must be harmless — the session-end path and the user
    # clicking Stop can both reach it.
    await handle.disable()


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


async def _check_all_files_are_delivered(s: ConversationSurface) -> None:
    files = [OutboundFile(display_name=f"f{i}.txt", blob=b"data") for i in range(5)]
    await s.deliver_files(files)
    delivered = _delivered_files(s)
    assert len(delivered) == len(files), (
        f"{len(files)} files were handed over but {len(delivered)} arrived — "
        "a surface that batches must still send every batch"
    )


async def _check_empty_file_list_is_a_noop(s: ConversationSurface) -> None:
    await s.deliver_files([])
    assert not _delivered_files(s), "delivering an empty list must send nothing"


# ---------------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------------


async def _check_rename_never_raises(s: ConversationSurface) -> None:
    """Rename is a no-op where threads have no name — Teams reply chains do
    not. It must degrade quietly rather than break a session."""
    await s.rename("a new title")


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------
#
# The contract needs to see what a surface actually emitted. Rather than add
# recording to the protocol — which would make every production implementation
# carry test scaffolding — a surface under test exposes two optional hooks.
# A surface that offers neither is still checked for "did not raise"; it simply
# skips the assertions that need evidence.


def _sent_text(surface: ConversationSurface) -> list[str]:
    return list(getattr(surface, "conformance_sent_text", None) or [])


def _delivered_files(surface: ConversationSurface) -> list[str]:
    return list(getattr(surface, "conformance_delivered_files", None) or [])


_CHECKS: list[tuple[str, Callable[[ConversationSurface], Awaitable[None]]]] = [
    ("identity", _check_identity),
    ("capabilities are sane", _check_capabilities_are_sane),
    ("send_text round-trips", _check_send_text_roundtrip),
    ("long text is split to fit", _check_long_text_is_split_to_fit),
    ("empty text sends nothing", _check_empty_text_sends_nothing),
    ("stream accumulates", _check_stream_accumulates),
    ("stream finalize is idempotent", _check_stream_finalize_is_idempotent),
    ("every notice level is accepted", _check_notice_is_accepted),
    ("activity lifecycle", _check_activity_lifecycle),
    ("activity cancel is idempotent", _check_activity_cancel),
    ("status transitions", _check_status_transitions),
    ("choice returns an offered value", _check_choice_returns_an_offered_value),
    ("single select returns at most one", _check_single_select_returns_at_most_one),
    ("form answers only known keys", _check_form_answers_only_known_keys),
    ("interrupt handle is idempotent", _check_interrupt_handle),
    ("all files are delivered", _check_all_files_are_delivered),
    ("empty file list is a no-op", _check_empty_file_list_is_a_noop),
    ("rename never raises", _check_rename_never_raises),
]


# ---------------------------------------------------------------------------
# The whole frontend
# ---------------------------------------------------------------------------
#
# ``check_surface`` covers one conversation. This covers the object that hands
# them out — the seam a scheduler, a webhook or the REST API uses to reach a
# conversation without knowing which platform it lives on. The obligations are
# few but easy to get subtly wrong, and each one is something a caller silently
# depends on:
#
#   * a conversation resolves to the same key it was created with, or the
#     scheduler's follow-up posts land in a different thread than the one the
#     session ran in;
#   * an unknown key returns None rather than raising, because "that thread was
#     deleted" is ordinary and must not take a scheduler loop down;
#   * every surface handed out declares this frontend's name, so a persisted
#     ThreadKey can be traced back to the platform that minted it.

FrontendFactory = Callable[[], Awaitable[SessionFrontend]]


async def check_frontend(make_frontend: FrontendFactory, *, parent_id: str) -> ConformanceReport:
    """Run every contract check against frontends produced by *make_frontend*.

    Args:
        make_frontend: Async callable returning a ready frontend, called once
            per check so leftovers cannot leak between them.
        parent_id: A channel/team the frontend may create conversations under.

    Returns:
        A report. ``report.ok`` is the verdict; ``report.summary()`` explains.
    """
    report = ConformanceReport()
    for name, check in _FRONTEND_CHECKS:
        try:
            frontend = await make_frontend()
            await check(frontend, parent_id)
        except AssertionError as exc:
            report.failures.append(f"{name}: {exc}")
        except Exception as exc:  # noqa: BLE001 — an unexpected raise is also a failure
            report.failures.append(f"{name}: raised {type(exc).__name__}: {exc}")
        else:
            report.passed.append(name)
    return report


async def _check_frontend_is_named(frontend: SessionFrontend, parent_id: str) -> None:
    assert frontend.name, "SessionFrontend.name must not be empty"


async def _check_created_conversation_resolves(frontend: SessionFrontend, parent_id: str) -> None:
    created = await frontend.create_surface(parent_id=parent_id, title="conformance")
    resolved = await frontend.resolve_surface(created.thread_key)
    assert resolved is not None, "a conversation just created did not resolve"
    assert resolved.thread_key == created.thread_key, (
        f"resolve_surface returned key {resolved.thread_key}, expected {created.thread_key}"
    )


async def _check_surfaces_carry_the_frontend_name(
    frontend: SessionFrontend, parent_id: str
) -> None:
    created = await frontend.create_surface(parent_id=parent_id, title="conformance")
    assert created.frontend == frontend.name, (
        f"surface reports frontend {created.frontend!r}, "
        f"but it came from {frontend.name!r} — a persisted ThreadKey could not be traced back"
    )


async def _check_unknown_key_is_none_not_an_error(
    frontend: SessionFrontend, parent_id: str
) -> None:
    """A deleted thread is ordinary. It must not take the caller down."""
    missing = await frontend.resolve_surface(_UNUSED_THREAD_KEY)
    assert missing is None, f"resolve_surface invented a surface for an unknown key: {missing!r}"


async def _check_two_conversations_do_not_share_a_key(
    frontend: SessionFrontend, parent_id: str
) -> None:
    first = await frontend.create_surface(parent_id=parent_id, title="conformance one")
    second = await frontend.create_surface(parent_id=parent_id, title="conformance two")
    assert first.thread_key != second.thread_key, (
        "two conversations were given the same ThreadKey — sessions would overwrite each other"
    )


#: A key no frontend should ever have minted. Large enough to sit outside any
#: real Discord snowflake yet inside SQLite's signed 64-bit range.
_UNUSED_THREAD_KEY = 4_000_000_000_000_000_001

_FRONTEND_CHECKS: list[tuple[str, Callable[[SessionFrontend, str], Awaitable[None]]]] = [
    ("frontend is named", _check_frontend_is_named),
    ("a created conversation resolves", _check_created_conversation_resolves),
    ("surfaces carry the frontend name", _check_surfaces_carry_the_frontend_name),
    ("unknown key resolves to None", _check_unknown_key_is_none_not_an_error),
    ("two conversations do not share a key", _check_two_conversations_do_not_share_a_key),
]
