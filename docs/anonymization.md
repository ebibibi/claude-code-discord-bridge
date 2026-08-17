# Anonymization gateway

Replace the parts of a message that identify *your* organisation, send the rest
to the strongest external model you can reach, and put the real names back in
the answer.

The intent is narrow and worth stating plainly: the safe model your company
provides is often not good enough, and the model people actually want to use
becomes a policy violation the moment internal information is pasted into it.
The result is that it gets used anyway, unreported. This feature exists to make
the safe path the default path — not to claim the problem is solved.

## What it does

```
Discord message
   │
   ▼
[1] rule-based replacement ── deterministic, reversible, no model involved
   │
   ▼
[2] local model inspection ── looks for proper nouns the rules missed
   │                          (never rewrites; only reports)
   ▼
[3] policy decision ──────── block / warn / off
   │
   ▼
   claude / codex CLI ──────► external API
   │
   ▼
[4] restore aliases in the answer, then show it to the user
```

Everything except step 3's outbound call happens on your machine. The mapping
table — the only thing that can undo the replacement — never leaves it.

## Why the rules replace and the model only inspects

Handing the replacement itself to a model is the obvious design and the wrong
one:

- **It is not deterministic.** The same hostname becomes a different alias on
  each run, so the answer can no longer be mapped back.
- **It summarises.** Detail disappears — and detail is the reason you asked an
  AI in the first place.

A rule table replaces the same string the same way forever, which is what makes
restoration possible. The local model is good at something else: noticing a
proper noun nobody wrote a rule for. So it reports, and a human decides.

## Turning it on

The feature is off until a rules file exists. Create one at
`~/.ccdb/anonymize-rules.json` (see
[`examples/anonymize-rules.example.json`](../examples/anonymize-rules.example.json)):

```json
{
  "terms": [
    { "value": "Contoso Japan", "category": "org" },
    { "value": "Contoso", "category": "org" },
    { "value": "Taro Yamada", "category": "person" }
  ],
  "patterns": [
    { "regex": "srv-[a-z0-9\\-]+", "category": "host" },
    { "regex": "[a-z0-9\\-]+\\.onmicrosoft\\.com", "category": "domain" }
  ],
  "builtins": ["email", "ipv4"]
}
```

- `terms` — literal strings, matched case-insensitively. Longer terms win, so
  `Contoso Japan` is replaced as a unit rather than as `org-001 Japan`.
- `patterns` — regular expressions, for naming conventions.
- `builtins` — `email` and `ipv4` are enabled by default; pass `[]` to disable.

Categories decide the shape of the alias, so the external model still sees "a
hostname" or "an address" and can reason structurally:

| category | alias |
|---|---|
| `org`, `person`, `host`, `project`, `term` | `org-001`, `person-002`, … |
| `domain` | `example-001.invalid` |
| `email` | `person-001@example.invalid` |
| `ipv4` | `203.0.113.1` (RFC 5737 documentation range) |

Then restart the bot, or just save the file — the rules are re-read when the
file's mtime changes.

## The local inspector

Any Ollama-compatible endpoint works. A small model is enough; the task is
"does this still contain a proper noun", not reasoning.

```bash
CCDB_ANONYMIZE_INSPECTOR_URL=http://127.0.0.1:11434
CCDB_ANONYMIZE_INSPECTOR_MODEL=qwen3:4b
```

Suspects it reports are filtered twice before a human sees them: anything that
does not literally appear in the text is dropped (hallucination), and anything
that turns out to be one of our own aliases is dropped too. That second filter
is not paranoia — a local model does report `person-001@example.invalid` as a
real address even when the prompt tells it not to, and under the block policy
that false positive stops a message that was already safe.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CCDB_ANONYMIZE` | `1` | Set to `0` to disable even with a rules file present |
| `CCDB_ANONYMIZE_RULES` | `~/.ccdb/anonymize-rules.json` | Rules file; its absence disables the feature |
| `CCDB_ANONYMIZE_MAPPING` | next to the rules file | The mapping table. **Back this up, never share it** |
| `CCDB_ANONYMIZE_SCOPE` | `escalation` | `escalation` (only `/ask`) or `all` (every backend too) |
| `CCDB_ANONYMIZE_POLICY` | `block` | `block` / `adopt` / `warn` / `off` |
| `CCDB_ANONYMIZE_INSPECTOR_URL` | `http://127.0.0.1:11434` | Ollama-compatible endpoint |
| `CCDB_ANONYMIZE_INSPECTOR_MODEL` | `qwen3:4b` | Inspection model |
| `CCDB_ANONYMIZE_INSPECTOR_TIMEOUT` | `30` | Seconds |
| `CCDB_ANONYMIZE_AUDIT` | next to the rules file | JSONL audit trail |
| `CCDB_ANONYMIZE_AUDIT_ENABLED` | `1` | Set to `0` to write no audit trail |
| `CCDB_ANONYMIZE_AUDIT_TEXT` | `1` | Set to `0` to log metadata without the sent text |

### Scope

By default the gateway sits on **the escalation hop only** — `/ask`. The agent
itself is expected to run on a model you control (see
[the local backend](local-backend.md)), and anonymizing that traffic buys
nothing while making the local model reason about `host-001` instead of the
real name. Worse, with the fail-closed default it would stop every thread
whenever the local inspector is unreachable.

Set `CCDB_ANONYMIZE_SCOPE=all` to wrap every backend as well. That is the right
setting when your agent still runs against a vendor by default — but be aware
of what it does *not* cover: the CLI reads local files and sends them itself.
See "What it does not protect".

Policies:

- **`block`** (default) — nothing is sent while the inspector reports a
  leftover, and nothing is sent when the inspector cannot be reached. Fail
  closed: an inspector that is down must not silently become "no inspection".
- **`adopt`** — mint an alias for each reported leftover, replace it, and send.
  The term is written to the mapping table, so from then on it is replaced by
  the table like any rule term — one detection is permanent, and the model is
  not asked about it again. Still fail-closed on an unreachable inspector: it
  can only adopt what was actually reported.
- **`warn`** — send anyway, but say so in the thread and in the audit log.
- **`off`** — skip inspection entirely. Rule-based replacement still runs.

### Why `adopt` does not break the "no model chooses aliases" rule

The model still only *reports*. The mapping table mints the alias and performs
every substitution, exactly as for a rule term, so the answer restores. What
changes is the consequence of a hit: `block` demands the operator edit the
rules file before anything can be sent, which in practice means a new customer
name stops the command until someone maintains a list by hand. `adopt` closes
that loop automatically while keeping the same determinism.

The trade-off worth knowing: a false positive is replaced too. An over-eager
inspector that calls `Azure` an organisation will alias it, and the external
model then answers about `org-004`. The sent text is shown in the reply
(`show_sent`), which is where that shows up.

A malformed rules file raises instead of disabling the feature. Sending real
names because of a missing comma is the exact failure this exists to prevent.

## What it does not protect

Say this part out loud to anyone who asks:

- **Only the message text is anonymized.** Claude Code and Codex read files and
  run commands on your machine, and what they read goes to the API directly.
  This gateway sits on the chat path, not on the API path.
- **Replacement misses are possible.** That is why the inspector and the block
  policy exist, and why neither is a guarantee.
- **The body still goes out.** Identifiers are removed; the sentences are not.
  If the text itself is the secret, this is the wrong tool.
- **It cannot stop copy-paste.** Someone pasting into a personal AI account in
  a browser is outside this path entirely.

What you get is not "safe". It is *describable*: you can say exactly what was
sent, and show the log.

## Files it owns

| File | Contents | Sensitivity |
|---|---|---|
| `anonymize-rules.json` | What to replace | Names your organisation — keep it internal |
| `anonymize-mapping.json` | alias ⇄ real name | **Highest.** Losing it makes old answers unreadable; leaking it undoes the anonymization |
| `anonymize-audit.jsonl` | What was sent, when, by which thread | Contains anonymized text only |

The mapping table and audit log are created with `0600` permissions.
