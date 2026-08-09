"""What Microsoft Teams can actually do, as numbers rather than folklore.

These values were previously written down only inside the conformance tests,
which is the wrong place for them: a test that owns the numbers proves the
*test's* idea of Teams is self-consistent, not the shipped frontend's. They
live here now, and the tests import them, so there is exactly one Teams column
and it is the one the surface will read at runtime.

Every field that is not a platform default carries the reason it is set.
"""

from __future__ import annotations

from claude_code_core.frontend import SurfaceCapabilities

__all__ = ["TEAMS_CAPABILITIES"]

#: Teams' own limits, as of 2026-08.
#:
#: * ``max_message_chars`` — a Teams message may reach roughly 100 KB; 80 KB is
#:   the documented safe ceiling once the HTML envelope is counted. Two orders
#:   of magnitude more than Discord, which is why a Teams answer arrives as one
#:   message where Discord's arrives as fifteen.
#: * ``supports_reactions`` — a *bot* cannot add a reaction. Discord's status
#:   dots therefore have no Teams equivalent; the status row of the session
#:   card carries that information instead.
#: * ``live_update_budget_per_hour`` — 1,800 operations per hour per
#:   conversation. This, not the preferred pace, is what governs streaming:
#:   ``min_update_interval`` resolves to 2.0s, so a naive once-a-second live
#:   timer would exhaust a long session's budget partway through.
#:   https://learn.microsoft.com/microsoftteams/platform/bots/how-to/rate-limit
#: * ``supports_slash_commands`` — Teams has no slash commands for bots. The
#:   manifest's ``commandLists`` is a menu of suggested message text, not a
#:   command surface, so the text-command router in PR11 is not optional.
#: * ``file_delivery`` — a bot cannot attach a file to a channel message; it
#:   uploads and shares a link. Discord's inline attachment has no counterpart.
#: * ``monospace_width`` — Teams' code block is far wider than Discord's, so
#:   tables that Discord has to fold survive as tables here.
#: * ``monospace_cjk_is_double_width`` — left at the conservative default.
#:   Until it is measured on a real client, CJK tables fall back to the
#:   vertical layout: plain, but never visibly misaligned.
#:
#: ``supports_tables`` / ``supports_headings`` / ``supports_inline_images`` stay
#: at their "no" defaults on purpose. Teams *can* render all three, but only
#: through markup the surface does not emit yet; a capability is a promise about
#: this implementation, not about the platform's brochure. They are raised in
#: the PR that actually renders them.
TEAMS_CAPABILITIES = SurfaceCapabilities(
    max_message_chars=80_000,
    monospace_width=100,
    supports_message_edit=True,
    supports_message_delete=True,
    supports_reactions=False,
    live_update_budget_per_hour=1800,
    stream_min_interval=1.0,
    max_files_per_message=1,
    file_delivery="link",
    supports_slash_commands=False,
    supports_pinned_dashboard=False,
    supports_thread_rename=False,
)
