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

The normal bot launcher owns that private-side lifetime. To run Teams beside
Discord in the same process, add these values to the deployment environment:

```bash
CCDB_FRONTENDS=discord,teams
CCDB_TEAMS_QUEUE_URL='https://acct.queue.core.windows.net/relay?<SAS>'
CCDB_TEAMS_APP_PASSWORD='...'
```

The remaining `CCDB_TEAMS_*` identity values are the same ones used to build
the manifest. On startup the launcher creates one shared HTTP client, the
`BotConnector`, `TeamsFrontend`, and `ActivityPuller`; on shutdown it stops the
poller before closing the client. Discord's gateway connection remains active
throughout. The private host still opens no Teams listener.

`CCDB_FRONTENDS` defaults to `discord`, so upgrading an existing Discord-only
deployment does not start a queue poller. Unknown and duplicate frontend names
are rejected at startup.

The queue SAS URL is a credential in a URL: it never appears in a log line, an
exception, or a `repr`. The failures raised here name the operation and the
status code and nothing else.

## Measured, on a real deployment

Azure Container Apps in `japaneast`, 0.25 vCPU / 0.5 GiB, receiver only. Times
are from the Teams transcript — user message to bot reply, end to end through
Teams, the Bot Connector, the receiver, the queue, the poller at home, and back
out to the Bot Connector.

| | latency |
|---|---|
| home endpoint behind a Cloudflare tunnel (no relay) | 1.8 s |
| **through the relay**, first message (outbound token not yet cached) | 2.1 s |
| **through the relay**, steady state | **0.8 s / 1.1 s** |

The relay is *faster* than the tunnel it replaced. The queue hop costs less
than the tunnel did, and the receiver sits in the same region as the tenant.

The receiver's own share, measured from the internet: **68 ms median** to
verify and answer (8 samples, warm).

### Cold start, and why `min-replicas` is 1

Scale-to-zero is the wrong default here, and not for cost reasons. Measured on
this deployment, after the app had scaled to zero:

| | latency |
|---|---|
| first request after scale-to-zero | **20.9 s** |
| the very next request | **0.069 s** |

20.9 s is not a slow reply. Teams gives the messaging endpoint a short budget,
and a **card press is answered from the HTTP response body within seconds** —
so the first press after an idle period shows the user an error even though
everything downstream worked perfectly. The failure mode is not "slow", it is
"the first person to press a button after lunch sees an error, and nobody can
reproduce it".

Running one replica always-on removes the variable, and the bill says it is not
the expensive part of this deployment.

### What it costs to leave one replica running

Container Apps bills a replica that is *running but not serving a request* at an
idle rate — for vCPU that is **1/8** of the active rate. At the `japaneast`
retail price (2026-08), 0.25 vCPU and 0.5 GiB for a 730-hour month:

| | monthly |
|---|---|
| Container App, `min-replicas=1`, idle | **$4.3 – $5.9** |
| Container Registry, Basic — one image | **$5.1** |
| Storage queue, Bot Service (F0), Container Apps environment | ~$0 |

The range on the first line is whether the monthly free grant (180,000 vCPU-s,
360,000 GiB-s) is credited against idle usage; the honest answer is "assume it
is not".

Note what that table says: **holding the image costs about as much as running
it.** A registry is billed per day for existing, and the compute is billed at
the idle rate for a container that spends its life asleep. If this bill needs to
come down, the receiver is the wrong place to look — publish the image to a free
public registry instead. Nothing in it is secret; that is the point of the
Dockerfile.

The measured deployment was subsequently moved from Azure Container Registry
to `ghcr.io/ebibibi/ebi-agent-chat-relay:v2`, and the dedicated Basic registry
was deleted. The image digest remained identical across registries. A fresh
Container Apps replica was then pulled and started after the Azure registry and
its credentials were gone; three health checks completed in 71–74 ms. This
removes the $5.1/month registry line from the table above.

GitHub Container Registry makes command-line-published packages private by
default, and changing package visibility is a web-settings operation rather
than a Packages REST API operation. A private image costs the same ($0) but
requires a registry credential in Container Apps. Use a dedicated token without
`repo` or `delete:packages`; if the package is later made public, remove that
credential and restart the revision once to prove anonymous pull works before
discarding it.

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
