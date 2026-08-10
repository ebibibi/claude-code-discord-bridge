"""Giving Teams an inbound endpoint without giving the session host one.

Discord worked because the transport was outbound only: the bot dialled out,
and the machine running sessions never appeared on the internet's attack
surface. Teams requires inbound HTTPS — but *where* that inbound lands is a
choice, and this package is the choice.

::

    Teams ──HTTPS──▶ receiver (Azure, disposable) ──▶ queue
                                                        │
    session host ─────────────outbound poll─────────────┘
    session host ─────────────outbound HTTPS──────────▶ Bot Connector (replies)

The session host opens **no** listening port. It polls a queue it can reach
outbound, and it replies straight to the Bot Connector, also outbound. That is
the Discord shape again, restored on a platform that does not offer it.

What the receiver is allowed to know
------------------------------------
Almost nothing. It holds the bot's *application id* — public, printed in the
manifest — and a credential for writing to one queue. It does **not** hold the
client secret, because it never replies. A compromised receiver yields the
messages that pass through it from that moment on; it does not yield the
ability to speak as the bot, to read past conversations, or to reach anything
on the session host.

That asymmetry is the entire point, and it is why the receiver validates the
inbound token itself rather than deferring: work done there is work the session
host never has to be exposed to do.

The cost, stated plainly
------------------------
A card press (``invoke``) is answered from the HTTP response body, and the
receiver has to answer it in seconds without knowing whether the prompt is
still live. So it acknowledges every well-formed press and enqueues it. The
user always sees the press succeed, even for a prompt that has already timed
out; the *effect* is still refused correctly, by
:class:`~claude_teams.interactions.InteractionRegistry` on the session host,
where the prompt actually lives. Feedback precision is traded for keeping the
session host off the internet — see ``docs/teams-relay.md``.
"""

from __future__ import annotations

from .envelope import Envelope
from .puller import ActivityPuller
from .queue import ActivityQueue, MemoryQueue, QueuedItem
from .receiver import RelayReceiver

__all__ = [
    "ActivityPuller",
    "ActivityQueue",
    "Envelope",
    "MemoryQueue",
    "QueuedItem",
    "RelayReceiver",
]
