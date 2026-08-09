# Running Teams without putting the session host on the internet

Discord was safe in a way that had nothing to do with the code: the transport
was **outbound only**. The bot dialled out over a websocket, and the machine
running coding-agent sessions never appeared on the internet's attack surface.

Teams requires inbound HTTPS. But *where* that inbound lands is a choice.

```
Teams ──HTTPS──▶ receiver (Azure, disposable) ──▶ queue
                                                    │
session host ─────────────outbound poll─────────────┘
session host ─────────────outbound HTTPS──────────▶ Bot Connector (replies)
```

The session host opens **no listening port**. It polls a queue outbound and
replies straight to the Bot Connector, also outbound. That is the Discord shape
again, restored on a platform that does not offer it.

## What each side holds

| | receiver (public) | session host (private) |
|---|---|---|
| bot application id | yes — it is public, printed in the manifest | yes |
| **client secret** | **no** | yes |
| queue credential | write | read + delete |
| route to the other side | **none** | outbound only |
| can reply as the bot | **no** | yes |
| can start a session | **no** | yes |

A compromised receiver yields the messages passing through it from that moment
on. It does not yield the ability to speak as the bot, to read past
conversations, or to reach anything on the session host. That asymmetry is the
whole design.

## Why the receiver verifies rather than forwarding

Forwarding unverified bodies would make the *queue* the trust boundary and the
session host the thing that has to check — which needs the Bot Connector's keys
on the private machine and fills the queue with attacker-controlled junk.
Verifying at the edge means the queue only ever contains activities Microsoft
signed, and the host spends its trust on one claim: that the receiver did its
job. The envelope records what was checked, so that trust is auditable rather
than assumed.

The envelope also carries the **token's** `serviceurl` claim, not the body's
copy — the token is the part Microsoft signs. That distinction is what stops a
replayed token from redirecting the host's authenticated outbound calls, and
moving the endpoint to another machine must not quietly lose it.

## The cost, stated plainly

**Card presses lose feedback precision.** Teams reads the HTTP response body as
the answer to a press, within seconds, and the receiver cannot know whether the
prompt is still live — the registry that knows lives on the host. So it
acknowledges every well-formed press and enqueues it. The user always sees the
press succeed, even for a prompt that expired; the *effect* is still refused
correctly, on the host. Feedback precision, traded for keeping the host off the
internet.

**Everything is at-least-once.** Acknowledgement is separate from delivery, so a
host that dies mid-handler gets the message again rather than losing it — a
user's message that vanishes because a process restarted is indistinguishable
from a bot that ignored them. The cost is duplicates, which
`ActivityPuller` filters by activity id: running a session twice for one
message is worse than the crash that caused the redelivery.

**A poison message is dropped after a bounded number of tries**, loudly and with
its id. The alternative is retrying forever, which blocks every message behind
it.

## Running it

The public side, on a disposable container:

```bash
export CCDB_TEAMS_APP_ID=...          # public
export CCDB_TEAMS_TENANT_ID=...
export CCDB_TEAMS_PUBLIC_HOST=relay.example.com
export CCDB_TEAMS_QUEUE_URL='https://acct.queue.core.windows.net/relay?<SAS>'
python -m claude_teams relay --port 8080
```

No `CCDB_TEAMS_APP_PASSWORD`. If you find yourself setting one here, the
deployment has lost the property this document is about.

The private side polls with `ActivityPuller` and replies with the ordinary
`BotConnector`, which is where the client secret belongs.

The queue SAS URL is a credential in a URL: it never appears in a log line, an
exception, or a `repr`. The failures raised here name the operation and the
status code and nothing else.

## Why not the Azure SDK

Four HTTP calls — put, get, delete, and a `visibilitytimeout` that does the
lease. The project's guidance rules out heavy dependencies most users will
never need, and `claude_teams/relay/storage_queue.py` is smaller than the
import would be. Two things there are worth knowing:

- Queue Storage speaks **XML**, alone among these APIs, and parses with
  `defusedxml` — the document arrives over a network as bytes this process did
  not write, whoever is nominally at the other end.
- Pop receipts routinely contain `/` and `+`. They are encoded with
  `safe=""`; the default leaves `/` alone, and a half-encoded receipt makes the
  delete silently target something else, so the message comes back forever.
