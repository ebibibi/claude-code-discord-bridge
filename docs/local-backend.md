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
4. Pick a model. `/ollama list` shows what is already there, `/ollama use`
   selects one, and `/ollama pull` downloads a new one — see
   [Managing the runtime](#managing-the-runtime-ollama) below. `/model` and
   `/model install name:<model>` still work and do the same thing.

For example:

```text
/backend name:local
/ollama status
/ollama pull model:qwen3.6:35b-a3b use:true
```

The session embed turns olive and reads 🏠 Local model.

| Variable | Default | Meaning |
|---|---|---|
| `CCDB_LOCAL_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI-compatible endpoint serving `/v1/responses` |
| `CCDB_LOCAL_MODEL` | `gpt-oss:120b` | Model id to request |
| `CCDB_LOCAL_CODEX_HOME` | `~/.ccdb/local-codex-home` | ccdb-owned CLI home; regenerated on every spawn |

## Installing an Ollama model from Discord

`/model install name:<model>` appears as a real Discord subcommand and is
available only while the selected backend for the chosen scope is `local`.
ccdb derives Ollama's native `/api/pull` endpoint from
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

## Managing the runtime: `/ollama`

`/model` answers "which model do I want". It cannot answer the questions that
actually come up when the cloud backends are unavailable — what is installed,
what will fit, what is resident in memory right now, why the answers are bad.
Those live on Ollama's *native* API, and `/ollama` is a typed mirror of it, so
managing the runtime does not mean SSHing to the box.

| Command | What it answers |
|---|---|
| `/ollama status` | Is the server reachable, is the selected model installed, can it call tools, are skills wired up |
| `/ollama list` | Every installed model with size, parameters and capabilities; ▶ marks the selected one |
| `/ollama ps` | What is loaded **right now**, how much memory it holds, and how much of it is on the GPU |
| `/ollama show model:<m>` | Capabilities, quantization, and the model's maximum context |
| `/ollama pull model:<m> [use:true]` | Download a model, optionally selecting it when the download finishes |
| `/ollama rm model:<m>` | Delete a model and free its disk space |
| `/ollama use model:<m>` | Select an installed model for the `local` backend (`thread_only:true` to scope it) |

Every model argument is autocompleted, so none of this requires knowing Ollama
syntax. `list`/`ps`/`show`/`rm`/`use` suggest what is installed on the server;
`pull` suggests a curated shortlist of models that suit the Codex CLI, annotated
with size and marked `[installed]` when you already have one — any tag from
`ollama.com/library` is still accepted as free text.

The management calls are derived from `CCDB_LOCAL_BASE_URL` by replacing the
terminal `/v1`, so there is only ever one address to configure. A reverse-proxy
prefix (`https://gw/ollama/v1`) is preserved.

### Two numbers worth reading

**Tool calling.** Codex acts *only* through tool calls. A model that does not
advertise the `tools` capability will describe the edit it would make instead of
making it — which reads as "the local backend is broken" and is really "this
model cannot act". `/ollama list` flags such models `NO-TOOLS`, and `/ollama
use` warns before selecting one.

**`ON GPU` in `/ollama ps`.** Below 100% means the remainder of the model is
running on the CPU, which is roughly an order of magnitude slower. If a local
thread suddenly feels unusable and nothing else changed, check this first: it is
usually another model having been loaded alongside it.

## Skills, and why the local model seems to ignore them

The obvious hypothesis is that the separate `CODEX_HOME` costs you your skills.
**It does not** — measured on codex-cli 0.147.0, by reading the session rollout
files under `<CODEX_HOME>/sessions/`, which record exactly what was sent:

| Setup | Skills in the `developer` message |
|---|---|
| ccdb-owned `CODEX_HOME`, no `skills/` directory at all | **135** |
| A bare temporary `CODEX_HOME` | **135** |

codex-cli discovers `~/.codex/skills` and `~/.claude/skills` on its own,
regardless of `CODEX_HOME`, and injects a `<skills_instructions>` block naming
every one. A local thread gets the same ~15 KB skill index a cloud thread does.
Mirroring the directories into the ccdb home changes nothing; an earlier
revision of this document said otherwise and was wrong.

So when a local run ignores a skill, the instructions were there and the model
did not act on them. In testing, a 30B model answered "I have no skills
available" with a 14,728-character skill index in its context. That is a model
capability limit, not a wiring problem, and the levers that move it are:

1. **A bigger or more agentic model.** By far the largest effect. `/ollama list`
   and `/ollama pull` exist to make this cheap to try.
2. **A model that advertises `tools`.** Codex acts only through tool calls.
   `/ollama list` flags the ones that cannot.
3. **`APPEND_SYSTEM_PROMPT`.** A short, blunt directive ("before answering,
   check the skills list for a matching skill and read its SKILL.md") is
   followed far more reliably by a small model than a 15 KB index is. ccdb
   passes it to Codex and to `local` as `developer_instructions`, which arrives
   as a `developer` message ahead of the turn.

Verify what a run actually received rather than guessing — the rollout files are
the record:

```bash
python3 - <<'EOF'
import json, pathlib
newest = max(pathlib.Path.home().glob(".ccdb/local-codex-home/sessions/**/*.jsonl"),
             key=lambda p: p.stat().st_mtime)
for line in newest.open():
    payload = json.loads(line).get("payload", {})
    if payload.get("role") == "developer":
        for chunk in payload.get("content", []):
            print(chunk.get("text", "")[:2000])
        break
EOF
```

## Honest expectations

A local model is slower and weaker than a frontier model, and the gap shows up
as *worse tool use* before it shows up as worse prose. Reading one small file
and reporting its contents cost ~22,000 tokens in testing. Treat local mode as
the default for work that touches customer data, not as a free upgrade.

If the endpoint is unreachable, the run fails. It does **not** fall back to a
cloud model — a silent fallback would defeat the entire purpose.
