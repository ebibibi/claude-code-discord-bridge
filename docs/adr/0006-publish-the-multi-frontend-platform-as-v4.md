---
type: adr
id: ADR-0006
title: Publish the multi-frontend platform as version 4
decision: Treat the combined Discord and Microsoft Teams frontend contract plus the multi-backend platform as the v4 product boundary, while preserving 3.x runtime compatibility.
status: accepted
date: 2026-08-11
deciders: [Masahiko Ebi, Codex]
scope: repository
supersedes: ADR-0005
superseded_by:
---

# ADR-0006: Publish the multi-frontend platform as version 4

## Context

ADR-0005 correctly classified AG-UI *by itself* as a backward-compatible feature and released it
as 3.4.0. Since that decision, the Microsoft Teams work also reached its production boundary: the
surface contract, authenticated public receiver, queue relay, private `ActivityPuller`, simultaneous
Discord startup, and a live Teams → real agent → Teams round trip are complete.

The product is no longer accurately described as a Discord bridge with another optional backend.
There are now two independent public axes:

- frontend: Discord or Microsoft Teams; and
- backend: Claude Code, Codex, local, or AG-UI.

Teams also introduces an operator-visible deployment contract — Entra identity, Azure Bot,
public HTTPS receiver, queue credentials, private polling host, app manifest, and tenant consent.
That boundary needs a prominent release and migration-quality documentation, even though the
existing Discord default and identifiers remain compatible.

## Options considered

### Keep 3.4.x

Rejected. It is technically compatible but materially understates the change in product scope and
leaves operators likely to miss the Teams deployment and trust-boundary review.

### Release 3.5.0

Rejected. A minor version accurately describes the additive APIs, but not the deliberate change in
the product's public contract from one chat surface to a frontend × backend platform.

### Release 4.0.0 with an explicit compatibility statement

Accepted. The major version marks the new product and deployment boundary. Release notes must say
plainly that v4 does not intentionally remove the 3.x package name, command, environment variables,
stored data, REST routes, or Discord-only default.

## Decision

1. Publish the completed multi-frontend, multi-backend platform as version 4.0.0.
2. Make the frontend × backend model the primary README explanation.
3. Provide one end-to-end Teams operator guide covering the full Azure/Entra/relay/private-host path.
4. Keep the `claude-code-discord-bridge` distribution, `ccdb` command, Python import names,
   `CCDB_*` settings, storage layout, APIs, and default `CCDB_FRONTENDS=discord` behavior.
5. Continue using minor releases for an isolated, backward-compatible frontend or backend addition.
   A future major version still requires an explicit ADR; this combined product-boundary decision
   is not a blanket exception to Semantic Versioning.

## Consequences and trade-offs

### Positive

- External users can discover Teams and AG-UI as first-class capabilities instead of buried work.
- Operators are directed to the security and setup review that a public Teams endpoint requires.
- The new name, architecture, and release number tell the same product story.
- Existing Discord-only deployments can upgrade without a forced configuration migration.

### Negative

- Some users will assume “4.0” means a breaking API change, so every release surface must include
  the compatibility statement.
- Superseding ADR-0005 requires nuance: its SemVer reasoning remains correct for AG-UI alone, while
  its rejected v4 conclusion no longer covers the later combined platform milestone.

## Related

- [ADR-0001: Adopt Ebi Agent Chat Relay as the product name](0001-adopt-ebi-agent-chat-relay.md)
- [ADR-0004: Add AG-UI as an optional backend transport](0004-add-ag-ui-as-an-optional-backend.md)
- [ADR-0005: Classify new optional backends as minor releases](0005-classify-feature-backends-as-minor-releases.md)
- [Microsoft Teams setup](../teams-setup.md)
- [Issue #611](https://github.com/ebibibi/ebi-agent-chat-relay/issues/611)
