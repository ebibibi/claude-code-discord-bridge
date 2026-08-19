# Local-model backend

Run a thread entirely against a model on your own hardware: `/backend local`.
Same CLI, same tools, same Discord experience — the model is just somewhere you
control.

## Why this is not simply "point the CLI at Ollama"

It is tempting to assume that configuring a local endpoint means nothing leaves
the machine. It does not. Measured on codex-cli 0.145.0, with the model pinned
to a LAN Ollama and no cloud calls in the task:

| Configuration | Endpoints the CLI actually contacted |
|---|---|
| Default `~/.codex` | local model **and `chatgpt.com:443`** |
| Empty `CODEX_HOME`, logged out | **`chatgpt.com:443`** |
| `check_for_update_on_startup = false` + `[analytics] enabled = false` | **local model only** |

The connection survives having no credentials at all, so "I am not logged in"
is not the protection people assume it is. It comes from the startup update
check and analytics, and both are switchable.

So ccdb does not reuse `~/.codex`. It generates and owns a separate
`CODEX_HOME` (default `~/.ccdb/local-codex-home`) containing a `config.toml`
that pins the local provider and switches both off. The user's own Codex config
is untouched, and a change there cannot silently re-enable either setting for
local threads.

## What is guaranteed, and what is not

- **Checked on every spawn:** the generated config still contains both
  settings. If either is missing, the backend refuses to start rather than run
  a "local" thread that phones home.
- **Not enforced:** this is a configuration ccdb controls, not an OS-level
  egress rule. A future CLI version could add a new call home that these
  settings do not cover.

An egress allowlist (a dedicated UID plus firewall rules) would be stronger,
but it is Linux-only and machine-wide — the wrong shape for a framework other
people install on Windows and macOS. **Re-measure after upgrading the CLI**;
the table above is a measurement of one version, not a promise about all of
them.

The `openai` credentials in the ambient environment (`OPENAI_API_KEY`,
`OPENAI_BASE_URL`, `CODEX_API_KEY`) are stripped from the subprocess, so a
local thread cannot fall back to a paid endpoint by accident.

## Setup

1. Run Ollama, or another OpenAI-compatible local runtime that serves
   `/v1/responses`. Ollama does. codex-cli dropped `wire_api = "chat"`, so an
   endpoint that only offers chat completions will not work.
2. Point ccdb at it:

```bash
CCDB_LOCAL_BASE_URL=http://192.168.1.3:11434/v1   # note the /v1
CCDB_LOCAL_MODEL=gpt-oss:120b
# CCDB_LOCAL_CODEX_HOME=/home/you/.ccdb/local-codex-home   # optional
```

3. In Discord, select the backend: `/backend name:local`.
4. Either select a model already present in Ollama with `/model name:<model>`,
   or install and select one with `/model install:<model>`.

For example:

```text
/backend name:local
/model install:qwen3.6:35b-a3b-mtp-q4_K_M
```

The session embed turns olive and reads 🏠 Local model.

| Variable | Default | Meaning |
|---|---|---|
| `CCDB_LOCAL_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI-compatible endpoint serving `/v1/responses` |
| `CCDB_LOCAL_MODEL` | `gpt-oss:120b` | Model id to request |
| `CCDB_LOCAL_CODEX_HOME` | `~/.ccdb/local-codex-home` | ccdb-owned CLI home; regenerated on every spawn |

## Installing an Ollama model from Discord

`/model install:<model>` is available only while the selected backend for the
chosen scope is `local`. ccdb derives Ollama's native `/api/pull` endpoint from
`CCDB_LOCAL_BASE_URL`, asks Ollama to pull the model, and immediately
acknowledges the command so a large download does not exceed Discord's
interaction deadline.

When the pull succeeds, ccdb stores the model for the same scope as the command
and uses it for the next session. A global install also updates the shared
default runner immediately. If the pull fails, the previous model selection is
left unchanged.

The bot process must be able to reach the Ollama host's native API, not only its
OpenAI-compatible `/v1` routes. Model downloads can be large and consume
substantial disk space; Ollama remains responsible for registry access,
download progress, storage, and deduplication.

Model names are sent as JSON to Ollama, never through a shell. ccdb accepts the
normal Ollama `name[:tag]` and namespaced `namespace/name[:tag]` forms and
rejects whitespace, URL syntax, and control characters before starting a pull.

## Honest expectations

A local model is slower and weaker than a frontier model, and the gap shows up
as *worse tool use* before it shows up as worse prose. Reading one small file
and reporting its contents cost ~22,000 tokens in testing. Treat local mode as
the default for work that touches customer data, not as a free upgrade.

If the endpoint is unreachable, the run fails. It does **not** fall back to a
cloud model — a silent fallback would defeat the entire purpose.
