---
type: adr
id: ADR-0003
title: Anonymize by rule, inspect by model
decision: Organisation-identifying terms are replaced by a deterministic rule table before a prompt reaches an external CLI; a local model only reports replacement misses and never rewrites text.
status: accepted
date: 2026-08-08
deciders: [Masahiko Ebi, Claude]
scope: repository
supersedes:
superseded_by:
---

# ADR-0003: Anonymize by rule, inspect by model

## Context

The relay sends what a person types in a chat surface to an external CLI, which
sends it to an external model. In consulting and internal-IT work the useful
message is usually the one that names a customer, a server, and a person — the
message that policy forbids sending. The observed outcome is not abstention: the
strong external model gets used anyway, unreported, because the sanctioned
internal model is not good enough for the question.

Two mechanisms are available for removing the identifying parts before the text
leaves the machine:

1. ask a local model to rewrite the text so that identifiers are gone;
2. apply a rule table that maps each known identifier to a fixed alias.

A third component is also needed either way: something that notices identifiers
nobody anticipated.

## Decision

**A rule table performs the replacement. A local model only inspects the
already-replaced text and reports what it still sees. The roles are not
interchangeable.**

Concretely:

- Replacement is a pure function of `(rules, mapping table)`. The same input
  always produces the same alias, and the mapping table makes it reversible, so
  the answer can be restored before it is shown.
- The mapping table is stored locally with `0600` permissions and is never sent
  anywhere. It is the only artefact that can undo the replacement.
- The local model receives the anonymized text and returns a list of suspects.
  Its output is advisory input to a policy, never a rewrite.
- The policy defaults to fail-closed: an inspector that reports a leftover, or
  an inspector that cannot be reached at all, stops the send.
- The feature is inactive without a rules file, and a malformed rules file is an
  error rather than a silent downgrade.

## Consequences

### Why not let the model rewrite

- **Determinism.** A model produces a different alias per run, and an alias that
  changes cannot be mapped back. Restoration would be impossible, which removes
  the reason the feature is usable at all.
- **Detail loss.** Rewriting drifts into summarising, and the detail is what the
  question was about. A rule table preserves structure, configuration values and
  error ordering exactly, which is what the external model actually reasons over.
- **Auditability.** "These twelve strings were replaced by these twelve aliases"
  is a statement that can be checked. "A model rewrote it" is not.

### Accepted costs

- Rule quality is the product. A term nobody listed is a term nobody replaced,
  which is precisely why the inspector exists and why the default policy blocks.
- The inspector produces false positives — including, in the first end-to-end
  run against a real local model, the anonymizer's own placeholder
  `person-001@example.invalid`. Prompt wording did not fix this reliably, so
  suspects are filtered mechanically against the mapping table: if restoring a
  suspect changes it, we minted it and it cannot be a leak.
- The guarantee is bounded and must be stated as such. Only the message text is
  covered; the CLI still reads local files and sends their contents to the API
  on its own. The gateway sits on the chat path, not the API path. Extending the
  same table to the API path is a separate decision.

## Implementation

`claude_code_core/privacy/`, wired in by `create_backend()` via
`AnonymizingBackend`, a `SessionBackend` decorator — so Claude, Codex and any
backend added later are covered by one implementation. See
`docs/anonymization.md`.
