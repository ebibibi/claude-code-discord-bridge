# Explicit escalation — `/ask`

The companion to the [local-model backend](local-backend.md). A thread does its
work on a model you control; when it needs research, a second opinion or a
plan, **one** anonymized question goes out and one answer comes back.

```
/ask <question>
   │
   ▼
anonymization gateway ── identifying terms → stable aliases
   │
   ▼
external CLI, isolated ── no project context, no files, no tools
   │
   ▼
answer, restored to real names, in the thread
```

## Why this is stronger than anonymizing a normal chat turn

An ordinary session gives the external model your repository and a shell. The
[gateway](anonymization.md) can only anonymize the message text; everything the
agent then *reads* goes to the API on its own.

A consult has none of that. The external model receives one string and nothing
else, so **the audit log is a complete record of what left the machine** — which
is the property that makes the claim checkable rather than reassuring.

## The isolation, and why it is verified rather than documented

Every consult is checked immediately before the process starts. If any of these
does not hold, nothing is sent:

| | Why |
|---|---|
| `--setting-sources ""` | Otherwise CLAUDE.md, skills and memory are sent |
| Empty temporary directory as cwd | Nothing local to read |
| Every tool disallowed | No shell to escape the directory with |
| `--` before the prompt | Without it the variadic tool list eats the prompt |

The first row is the one that surprises people. Measured with `cwd=/home/ebi`
and every tool already disabled, changing **only** `--setting-sources`: asked
whether a term unique to the project's CLAUDE.md was present in its context,
the model answered "not present" with the flag and "present" without it. A
naive escalation ships the whole file — customer names included — no matter how
carefully the question itself was anonymized.

This is a *route*, not a procedure. `verify_isolation()` inspects the argv about
to be used, so a future refactor that drops a flag fails loudly instead of
quietly sending more than intended.

## Using it

`/ask` appears only when an anonymization rules file exists. Without rules
nothing would be replaced, and a command that silently forwards real names is
worse than no command.

```
/ask question: How do I debug a conditional access policy that blocks one host?
```

The reply shows the exact text that was sent (`show_sent`, on by default), then
the answer with your real names restored. Both are in the audit log.

## Limits

- **One question, no memory.** A consult does not resume; each one starts clean.
  That is deliberate — a growing conversation would accumulate context nobody
  audited.
- **Nothing is retried.** If the external CLI fails, you get the error.
- **The body still goes out.** Identifiers are replaced; the sentences are not.
  If the text itself is the secret, do not escalate it.
