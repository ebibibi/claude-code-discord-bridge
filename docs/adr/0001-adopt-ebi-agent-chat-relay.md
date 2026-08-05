---
type: adr
id: ADR-0001
title: Adopt Ebi Agent Chat Relay as the product name
decision: Use Ebi Agent Chat Relay as the product name and retain ccdb as a compatibility alias during a phased migration.
status: accepted
date: 2026-08-05
deciders: [Masahiko Ebi, Claude Code]
scope: repository
supersedes:
superseded_by:
---

# ADR-0001: Adopt Ebi Agent Chat Relay as the product name

## Context

The original name, **Claude Code Discord Bridge**, accurately described the first
implementation but no longer describes the product boundary:

- the runtime supports both Claude Code and OpenAI Codex;
- the frontend abstraction is intended to support Discord, Teams, and later surfaces;
- its distinguishing behavior is relaying interactive agent sessions while sharing a
  coordination ledger that lets parallel sessions detect collisions;
- deployment may be shared, customer-dedicated, or customer-hosted.

The existing short name, `ccdb`, is widely embedded in commands, environment variables,
database and attachment paths, API examples, service names, and operational habits. A
big-bang rename would create migration risk without improving runtime behavior.

## Options considered

### Keep Claude Code Discord Bridge

Rejected as the product name because it hard-codes both one backend and one surface.
Keeping it would make Teams and additional agent backends look incidental.

### Agent Bridge

Rejected because the words are generic and crowded. The name is difficult to search for
and does not express the conversational relay behavior.

### Session Bridge

Rejected because it is architecturally accurate but unclear to people discovering the
product. It describes an implementation concept rather than the user-facing job.

### CodeRelay

Rejected because it is memorable but narrows the product to code even though sessions
also handle operations, research, documents, scheduling, and other agent work.

### Ebi Agent Chat Relay

Accepted because it is distinctive, backend-neutral, surface-neutral, and describes the
observable job: relaying agent conversations and their work across chat surfaces.

## Decision

1. The product name is **Ebi Agent Chat Relay**.
2. `ebi-agent-chat-relay` is the candidate repository and Python distribution name.
   Availability must be checked again immediately before either external rename or
   publication.
3. `ccdb` remains a supported migration alias.
4. The migration is additive and phased. No release may rename every public identifier
   at once.
5. Existing public identifiers—including the `ccdb` command, `CCDB_*` environment
   variables, API routes, persisted data locations, and Python import paths—remain
   supported until a separate removal ADR approves a major-version transition.

The implementation sequence and compatibility gates are defined in the
[phased rename plan](../RENAME_PLAN.md).

## Rationale

The chosen name separates the stable product concept from replaceable technical details.
It remains accurate when a customer chooses Discord or Teams, Claude or Codex, and a
shared or isolated deployment.

An additive migration protects existing installations and automation. The old name is
not merely documentation: it is part of scripts, configuration, service management, and
stored paths. Treating those identifiers as compatibility contracts lets branding move
without turning a naming decision into an outage.

## Consequences and trade-offs

### Positive

- The name remains accurate as backends and chat surfaces expand.
- Searchability and ownership are stronger than with generic “bridge” names.
- Existing users can upgrade without an immediate configuration or data migration.
- Each migration phase has an independent rollback point.

### Negative

- Documentation and support will carry two names during the transition.
- Some legacy identifiers may remain indefinitely.
- Publishing or renaming external artifacts requires additional availability,
  redirect, packaging, and consumer verification.

## Non-goals

This ADR does not:

- rename the repository, package, CLI, import module, environment variables, API routes,
  service, or data paths now;
- choose a replacement command for `ccdb`;
- change deployment topology or customer isolation policy;
- implement the Teams surface;
- authorize a service restart.

## Related

- [Phased rename plan](../RENAME_PLAN.md)
- [Design decisions](../DESIGN_DECISIONS.md)
- [Issue #571](https://github.com/ebibibi/claude-code-discord-bridge/issues/571)
