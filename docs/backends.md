# Choose an agent backend

Ebi Agent Chat Relay separates the **frontend** where a person talks from the **backend** that
does the work. Discord and Microsoft Teams use the same session ledger, coordination layer, and
backend factory. Selecting a backend therefore does not require a different bot or a different
Teams app.

## Supported combinations

| Backend | Transport | Authentication | Best fit |
|---|---|---|---|
| Claude Code | local `claude` CLI | the CLI's existing login | Claude-native coding workflows |
| OpenAI Codex | local `codex` CLI | the CLI's existing login | Codex coding and review workflows |
| Z.ai | local `claude` CLI, pointed at Z.ai's Anthropic-compatible endpoint | a dedicated Z.ai credential file | GLM models through the same CLI, without touching direct Anthropic credentials |
| Local | local `codex` CLI to an OpenAI-compatible `/v1/responses` endpoint | none by default | data that should stay on a controlled network |
| AG-UI | HTTP request plus JSON server-sent events | optional bearer token | custom and hosted agents that implement AG-UI |

All five work from both Discord and Microsoft Teams. The frontend controls message rendering,
buttons, files, and rate limits; the backend controls model execution and streamed events.

## Select a backend

Set the default before startup:

```dotenv
CCDB_BACKEND=codex
```

On Discord, switch an individual conversation without restarting:

```text
/backend claude
/backend codex
/backend zai
/backend local
/backend agui
```

These are Discord slash commands, and a conversation override is persisted in SQLite so it survives
a process restart. The normal Teams queue integration in v4 does not dispatch the text-command
router yet; Teams conversations use the configured/global backend. Set `CCDB_BACKEND` before
startup or change the global setting from the Discord administration surface when both frontends
run together.

Use `/model` and `/effort` to inspect or change backend-specific choices. Each backend remembers
its own model and reasoning setting.

## Claude Code and Codex

Install and authenticate the official CLI on the private session host before starting ccdb. The
relay reuses that CLI login; it does not copy a subscription token into Discord or Teams.

```bash
claude --version
codex --version
ccdb start
```

The default backend remains `claude`, so upgrading an existing deployment does not change which
agent receives the next turn.

## Z.ai

Z.ai serves the Anthropic Messages API, so the same Claude Code CLI runs against it unchanged once
the subprocess environment points at Z.ai — no separate CLI, no code changes.

```dotenv
CCDB_ZAI_ENV_FILE=/home/you/.ccdb/zai.env
CCDB_ZAI_MODEL=glm-5.2
```

`CCDB_ZAI_ENV_FILE` is a dedicated `KEY=VALUE` file holding the Z.ai credentials
(`ANTHROPIC_AUTH_TOKEN` and, if your account needs it, a regional `ANTHROPIC_BASE_URL`). Keep it
separate from any file used by `CCDB_CLI_ENV_FILE`: before applying it, ccdb pops
`ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` from the subprocess environment, so a Z.ai thread
never inherits — or silently falls back to — direct Anthropic credentials. Title-suggestion calls
pick a GLM model rather than an Anthropic alias, since Z.ai does not serve `haiku`.

Then set `CCDB_BACKEND=zai`, or enter `/backend zai` in Discord.

## Local

The local backend drives an OpenAI-compatible `/v1/responses` endpoint through a ccdb-owned Codex
configuration. It disables the measured startup update check and analytics rather than assuming
that “logged out” means “offline.”

```dotenv
CCDB_LOCAL_BASE_URL=http://127.0.0.1:11434/v1
CCDB_LOCAL_MODEL=gpt-oss:120b
```

Read [Local-model backend](local-backend.md) before using this for sensitive data. The guard is a
configuration control, not an operating-system egress firewall, and should be re-measured after
Codex CLI upgrades.

## AG-UI

Install the optional HTTP dependency and configure the exact run endpoint:

```bash
uv sync --extra agui
```

```dotenv
CCDB_AGUI_URL=https://agent.example.com/run
CCDB_AGUI_TOKEN=replace-with-a-dedicated-token
```

Then set `CCDB_BACKEND=agui`, or enter `/backend agui` in Discord. Whichever frontend supplies the
turn also supplies a stable AG-UI `threadId`, so the remote endpoint can preserve its own
conversation state.

See [AG-UI backend](agui-backend.md) for the event mapping, security boundary, and intentionally
unsupported protocol features.

## Mixing frontends and backends

Backend resolution belongs to the shared session layer, not the platform implementation. In v4,
Discord can set per-conversation overrides; Teams consumes the configured/global choice. A
deployment can therefore run, for example:

- a Discord thread on Claude Code;
- another Discord thread on Z.ai's GLM models;
- a third Discord thread on a local model;
- Teams conversations on the configured Codex default; or
- Teams conversations on an internal AG-UI agent when AG-UI is the configured/global backend.

The same AI Lounge, claims, collision detection, worktree rules, and session persistence cover all
of them. Frontend identity is stored with each session, so a Teams result cannot accidentally be
posted into a Discord thread with a numerically similar key.

## Security boundary

Every selected backend receives that conversation's prompts and attachments. Treat a remote AG-UI
endpoint, Z.ai, or local model host as part of the data-processing path. A customer-tenant Teams app does
not by itself keep data inside that tenant: messages still travel through Bot Framework, the public
receiver, the queue, the private session host, and the selected backend. Deploy the complete stack
inside the required boundary when the contract requires that literal property.
