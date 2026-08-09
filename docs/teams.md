# The Microsoft Teams frontend

> Status: output and interaction work. Configuration, the app package, inbound
> authentication, the endpoint, `TeamsSurface` and answerable prompts are here,
> and the shared conformance contract runs against the surface that ships. What
> is not here yet: transferring file contents. It says so rather than
> pretending.

Discord and Teams are siblings, not a base and a port. `claude_discord` and
`claude_teams` each implement the vocabulary in `claude_code_core.frontend`,
and neither imports the other. The same conformance contract runs against both,
which is what keeps "the Teams side is missing something" from being discovered
by a user months later.

## What is different about Teams

Discord's transport was outbound only: the bot dialled out and nothing on the
internet could reach it. Teams reverses that. **Your bot needs a public HTTPS
endpoint**, and behind that endpoint are coding-agent sessions with a shell. Two
consequences run through the whole package:

- Every inbound request is authenticated before its body is used for anything.
- Refusals are cheap and specific: oversized bodies, unsigned tokens, tokens for
  another bot, and tokens whose `serviceUrl` disagrees with the request body are
  all rejected before any work is scheduled.

The platform differences that shape the *experience* are recorded once, as
numbers, in `claude_teams/capabilities.py`:

| | Discord | Teams |
|---|---|---|
| message limit | 2,000 chars | 80,000 chars |
| bot reactions | yes | **no** |
| live updates | ~1 per 1.5 s | 1,800 per hour per conversation → 1 per 2 s |
| files | inline attachments | upload and share a **link** |
| slash commands | yes | **no** (the manifest's command list only pre-fills text) |

A caller never branches on the platform name; it asks the capabilities.

## Setting it up

### 1. Create the Entra application and Azure Bot

You need an application (client) id, its tenant, and a client secret. The Azure
Bot resource's *messaging endpoint* is the URL this package serves — the
generator prints it for you in step 3.

### 2. Configure

```bash
export CCDB_TEAMS_APP_ID=<the Entra application (client) id>
export CCDB_TEAMS_TENANT_ID=<the tenant the application lives in>
export CCDB_TEAMS_APP_PASSWORD=<the client secret>
export CCDB_TEAMS_PUBLIC_HOST=relay.example.com   # a bare host, not a URL
```

`CCDB_TEAMS_PUBLIC_HOST` is the one people get wrong. It goes into the
manifest's `validDomains`, which takes a host; a value with `https://` or a path
produces an app that installs and then receives nothing.

### 3. Generate the app package

```bash
pip install "claude-code-discord-bridge[teams]"
python -m claude_teams manifest --out dist/teams-app.zip
```

It prints the messaging endpoint to set on the Azure Bot resource, then upload
the zip to Teams. Icons are generated as placeholders; pass `--color-icon`
(192x192) and `--outline-icon` (32x32, white on transparent) before publishing
anywhere real.

The manifest is generated rather than checked in, so no tenant's ids live in
this repository and the package can never disagree with the environment the bot
actually runs with — both read the same variables.

Two things in the generated manifest are worth knowing about:

- **`ChannelMessage.Read.Group` (resource-specific consent).** Without it a
  channel-installed bot only sees messages that @mention it, which turns "drive
  a session by talking in the thread" into "prefix every message with a
  mention". The team owner grants it at install time.
- **`webApplicationInfo` (SSO).** Declared from the start, because adding it
  later is a fresh consent prompt for every tenant that already installed the
  app.

### 4. Expose the endpoint

Teams must reach `https://<host>/api/teams/messages`. A tunnel (Cloudflare
Tunnel, ngrok) in front of the machine running ccdb is the usual arrangement;
what matters is that the host in the manifest, the Azure Bot messaging
endpoint, and what actually answers are the same thing.

## What the surface does differently from Discord

| intent | Discord | Teams |
|---|---|---|
| a long answer | fifteen messages | **one** message |
| `open_activity` | an embed per tool call | a line on **one card** |
| `set_status` | an emoji on the user's message | the status row of that same card |
| `deliver_files` | inline attachment | **not yet** (see below) |

The card is the design. Discord posts an embed per tool call and edits it,
which is right there — editing is cheap and there is no hourly ceiling. Teams
allows 1,800 operations per hour per conversation, so the same approach would
spend a long session's entire budget on scrollback and then go silent. Here a
tool starting, the status changing and a tool finishing are three events and
one operation — repaint — and three of them inside one pacing interval cost one
request, not three.

`claude_teams/pacer.py` is what enforces that. It coalesces per target and
sends at most one update per interval, keeping the newest state rather than
the oldest. Per *target* matters: the card and a streaming reply are different
messages, and collapsing them onto one key would have a card repaint silently
swallow a pending stream edit — the answer would stop growing with nothing to
see.

## What is deliberately not claimed yet

**File contents are not transferred.** A bot cannot attach a file to a Teams
channel message; real delivery is an upload plus a consent card the user
accepts. `deliver_files` names the files and says the contents were not sent,
so a session cannot believe its output was handed over. The conformance run
therefore reports **17 passed, 1 failed**, and that one failure is pinned by
name in `tests/test_teams_conformance.py` — closing the gap is what makes the
test pass, and nothing else does.

## Answering a prompt

`prompt_choice` posts an Adaptive Card — a button per choice for a short list,
a dropdown for a long or multi-select one — and waits. `prompt_form` posts one
input per field. Pressing a control sends an **invoke**, which is not like a
message: Teams reads the HTTP response body as the answer, so a bare 200 shows
the user an error even though the press worked.

Everything in that payload is untrusted. The Bot Connector proves a Teams user
sent it; it proves nothing about the payload matching a card this process
posted. `claude_teams/interactions.py` applies four rules, in the order they
matter:

1. **The conversation must match.** Without this, someone who learns a prompt
   id can approve a tool run in a conversation they are not part of — and the
   session sees an ordinary approval with nothing odd about it.
2. **The value must have been offered**, or a crafted action returns any string
   as "what the user chose".
3. **Once only**, so a replay cannot answer the next prompt and a re-pressed
   Stop cannot interrupt the session after this one.
4. **Only declared keys come back from a form.** A card submit merges every
   input into the payload.

Refusals all look the same to the caller: one sentence, no reason. "Wrong
conversation" and "expired" are both free information to whoever is probing.

### Failing closed

When the clock runs out, `prompt_choice` applies the prompt's
`default_on_timeout` — for a tool-permission request, the denying choice. The
same fallback runs when the card could not be **posted at all**, because a
prompt nobody could see must not be safer to ignore than one nobody answered.

The shared contract deliberately does not check this: from outside, a surface
that denies on timeout and one that invents a denial return the same value.
`tests/test_teams_prompts.py::TestFailClosed` is where it is proved, by
withholding the answer.

### Stop

`offer_interrupt` puts a Stop control on the session card rather than posting a
button. Discord re-posts its Stop button to keep it in view because messages
scroll away from it; here the card is already the one message being kept
current. Disabling it takes the control off the card *and* stops honouring its
id, so a late press cannot interrupt whatever runs next.

## How a Teams conversation becomes a ccdb session

Teams conversation ids are strings (`19:...@thread.tacv2;messageid=...`), and
every table in ccdb keys a session on an integer. `issue_thread_key()` mints a
surrogate integer and the `frontend_threads` ledger records the pairing, so the
session ledger, AI Lounge, claims and collision detection see one keyspace
across both platforms — a Discord session and a Teams session can notice they
are editing the same file.

## Security notes

- Tokens are verified against the Bot Connector's published keys, with the
  signature algorithm pinned by this package rather than read from the token.
- The token's `serviceUrl` claim must match the activity body's. The body says
  where the reply goes, and the reply carries this deployment's credentials.
- Signing keys are refreshed when an unknown `kid` appears, but no more often
  than every five minutes — that trigger is reachable by anyone who can send a
  request.
- After a request is accepted, a downstream failure is logged and answered
  `200`. Teams redelivers on `5xx`, so returning one would have a user's message
  processed again on every retry.
- The client secret never enters the app package, a `repr()`, or an error
  raised from the token endpoint (whose own error text can quote the request).
