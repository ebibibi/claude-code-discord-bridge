---
type: adr
id: ADR-0004
title: Add AG-UI as an optional backend transport
decision: Implement AG-UI as an optional direct HTTP/SSE SessionBackend while retaining the relay's semantic frontend contract and operational core.
status: accepted
date: 2026-08-10
deciders: [Masahiko Ebi, Codex]
scope: repository
supersedes:
superseded_by:
---

# ADR-0004: Add AG-UI as an optional backend transport

## Context

Ebi Agent Chat Relay and CopilotKit Channels overlap at the visible product boundary: both connect
agents to chat surfaces. Their strongest responsibilities differ. Channels and AG-UI provide broad
agent-framework interoperability, while this relay already owns durable sessions, Discord and Teams
behavior, permissions, scheduling, coordination, restarts, and operational safety.

The relay needs an extension point for agents beyond the Claude and Codex CLIs without replacing
those mature operational capabilities or importing an entire TypeScript chat stack.

## Options considered

### Replace the relay with CopilotKit Channels

Rejected. It would discard mature session and operational behavior, require a cross-language
migration, and expand the credential and data-plane boundary substantially.

### Vendor the Channels packages

Rejected. Vendoring a large TypeScript implementation would create a permanent synchronization and
supply-chain maintenance burden while duplicating Discord and Teams adapters already present here.

### Depend on the AG-UI Python SDK in the core package

Rejected for the first transport layer. The wire contract needed by a client is small, while a
mandatory framework dependency would affect every Claude/Codex-only installation. The protocol can
be implemented and tested directly, with `aiohttp` kept behind an optional extra.

### Add a direct AG-UI `SessionBackend`

Accepted. It preserves the existing frontend-neutral `StreamEvent` and `ConversationSurface`
contracts while allowing a configured remote AG-UI agent to reuse the relay's chat surfaces and
operational controls.

## Decision

1. `AgUiBackend` is an optional `SessionBackend`, selected with `/backend agui` or
   `CCDB_BACKEND=agui`.
2. It posts the standard `RunAgentInput` JSON shape to one configured HTTP(S) endpoint and consumes
   JSON Server-Sent Events.
3. AG-UI lifecycle, text, reasoning, and tool events map into the existing semantic `StreamEvent`
   vocabulary. The frontend contract does not become AG-UI- or JSX-specific.
4. `aiohttp` is exposed through the `agui` optional dependency. Importing or running other backends
   does not require it.
5. The endpoint is an explicit trust boundary: URL credentials and redirects are rejected, bearer
   tokens are excluded from child CLI environments, response errors are bounded, and SSE frames
   have a size limit.
6. Unsupported interrupt/resume outcomes fail visibly. They must not appear as successful
   completions until a durable interaction store can recover them across restarts.
7. The remote agent owns conversation persistence by `threadId` in this first version. Full local
   transcript replay, state rendering, client tools, and protobuf are follow-up capabilities.

## Rationale

This is the smallest interoperable seam: agent frameworks can speak an open event protocol, while
the relay keeps the behavior users already depend on. Direct wire support also keeps the security
boundary inspectable and avoids coupling the Python core to one agent framework's release cadence.

Failing explicitly on interrupts is deliberate. Reporting “Done” would lose a human decision and
could leave a remote run suspended indefinitely; a visible limitation is safer than false success.

## Consequences and trade-offs

### Positive

- AG-UI agents gain Discord and Teams access without new platform adapters.
- Claude, Codex, and local backends retain their existing behavior and dependency footprint.
- The protocol adapter is isolated, unit-testable, and replaceable by an SDK later.
- Security controls apply at one outbound transport boundary.

### Negative

- The first version requires the remote endpoint to persist context by `threadId`.
- Human-in-the-loop AG-UI interrupts cannot yet resume through the relay.
- Supporting only JSON SSE excludes protobuf-only endpoints.
- Direct protocol maintenance must track compatible AG-UI specification changes.

## Related

- [Issue #605](https://github.com/ebibibi/ebi-agent-chat-relay/issues/605)
- [AG-UI backend guide](../agui-backend.md)
- [AG-UI documentation](https://docs.ag-ui.com/)
- [AG-UI protocol repository](https://github.com/ag-ui-protocol/ag-ui)
