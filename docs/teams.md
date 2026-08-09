# The Microsoft Teams frontend

> Status: skeleton. Configuration, the app package, inbound authentication and
> an echo endpoint are here. The `ConversationSurface` that turns an inbound
> message into a session is not yet — that is the next step.

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
