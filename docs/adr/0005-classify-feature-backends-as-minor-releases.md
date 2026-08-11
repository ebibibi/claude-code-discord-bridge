---
type: adr
id: ADR-0005
title: Classify new optional backends as minor releases
decision: Release a new backward-compatible SessionBackend as a SemVer minor version, even when the default merge automation initially creates a patch bump.
status: accepted
date: 2026-08-11
deciders: [Masahiko Ebi, Codex]
scope: repository
supersedes:
superseded_by:
---

# ADR-0005: Classify new optional backends as minor releases

## Context

The default post-merge workflow increments the patch component for every ordinary pull request.
PR #607 added AG-UI as a new optional `SessionBackend`, but the workflow therefore changed the
version from 3.3.36 to 3.3.37. The implementation is backward compatible and disabled unless
configured, yet it materially expands the public product capability and configuration surface.

The repository declares Semantic Versioning and already documents a manual release path for minor
and major versions.

## Options considered

### Keep 3.3.37

Rejected. A patch version communicates a backward-compatible bug fix. Adding a new backend and
public configuration surface is a backward-compatible feature, so a patch understates the change.

### Release 3.4.0

Accepted. A minor version is the SemVer classification for backward-compatible functionality. It
also preserves the existing 3.x compatibility promise because the default Claude, Codex, and local
backend behavior is unchanged.

### Release 4.0.0

Rejected. AG-UI is optional and additive. It does not remove or incompatibly change a public API,
configuration key, stored session format, or default behavior, so a major version would falsely
signal a breaking change.

## Decision

1. Correct the AG-UI release version to 3.4.0 and publish it through the documented `[release]`
   workflow.
2. Treat future new backward-compatible frontend or backend implementations as minor releases.
3. Reserve major releases for incompatible public API, configuration, persistence, or default
   behavior changes.
4. Keep the automatic patch bump for ordinary fixes; a feature PR that deserves a minor release
   must be followed by or prepared as an explicit release PR until the automation supports richer
   classification.

## Consequences and trade-offs

### Positive

- Version numbers communicate the compatibility and product significance of changes accurately.
- Existing 3.x users can adopt AG-UI without interpreting it as a breaking migration.
- The decision gives future backend additions a repeatable release rule.

### Negative

- The current automation cannot infer the release level from the merged change, so maintainers must
  use the explicit release path for minor versions.
- The intermediate 3.3.37 commit remains in history; 3.4.0 supersedes it as the intended release
  version rather than rewriting published history.

## Related

- [ADR-0004: Add AG-UI as an optional backend transport](0004-add-ag-ui-as-an-optional-backend.md)
- [PR #607](https://github.com/ebibibi/ebi-agent-chat-relay/pull/607)
- [Contributing: versioning](../ja/CONTRIBUTING.md#バージョニング)
