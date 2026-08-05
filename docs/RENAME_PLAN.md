# Ebi Agent Chat Relay: Phased Rename Plan

This plan implements [ADR-0001](adr/0001-adopt-ebi-agent-chat-relay.md) without a
big-bang rename. Every phase is independently releasable and reversible.

## Invariants

The following rules apply to every phase:

1. Existing installations must keep starting with their current configuration.
2. The `ccdb` CLI command remains supported.
3. Existing `CCDB_*` environment variables, REST routes, persisted database paths,
   attachment filenames, and Python imports remain valid.
4. A new identifier is additive before any old identifier is deprecated.
5. No old identifier is removed without a separate accepted ADR and a major release.
6. Branding changes do not authorize a bot restart or deployment migration.

## Phase 0 — Record the decision

**Scope**

- Add ADR-0001 and this plan.
- Keep all runtime, packaging, repository, and service identifiers unchanged.

**Exit gate**

- Documentation links are valid.
- The repository test and documentation checks remain green.

**Rollback**

- Revert the documentation PR. Runtime is unaffected.

## Phase 1 — Introduce the product brand

**Scope**

- Use **Ebi Agent Chat Relay** in the primary README, website, screenshots, and release
  notes.
- On first mention, write “Ebi Agent Chat Relay (formerly Claude Code Discord Bridge;
  `ccdb`)”.
- Update translated documentation through the existing documentation-sync workflow.

**Compatibility gate**

- Installation and command examples continue to use identifiers that actually exist.
- Search for the old product name and classify every occurrence as compatibility,
  history, translation, or stale branding before changing it.

**Rollback**

- Revert brand-only documentation and assets. No code or persisted data changes.

## Phase 2 — Add external artifact aliases

**Scope**

- Recheck GitHub and package-index availability immediately before acting.
- If the repository is renamed, verify GitHub redirects for clones, issues, releases,
  Actions, and raw documentation links.
- If a new `ebi-agent-chat-relay` distribution is published, make it install the same
  implementation while the existing distribution remains available.
- Keep the Python import package unchanged initially.

**Compatibility gate**

- A clean environment can install using both the legacy and new distribution names.
- Existing lockfiles can update without manual source edits.
- Git fetch, release automation, dependency graph updates, and documentation sync pass
  through the repository redirect.

**Rollback**

- Restore the prior repository name or stop advertising the new distribution.
- Keep the legacy artifact as the canonical installation path until failures are fixed.

## Phase 3 — Add command and configuration aliases

**Scope**

- Choose any new CLI command in a separate decision; do not infer one from the product
  initials.
- If added, route the new command and `ccdb` to the same entry point.
- Add new environment-variable aliases only with explicit precedence rules and conflict
  warnings.
- Continue writing existing data paths unless a migration design proves dual-version
  rollback safety.

**Compatibility gate**

- Contract tests run the same setup, start, and control-plane flows through both command
  names.
- Tests cover legacy-only, new-only, equal dual configuration, and conflicting dual
  configuration.
- Upgrade and rollback tests use a copy of a real legacy data directory.

**Rollback**

- Stop advertising the new aliases while retaining them in code.
- Prefer legacy configuration when rollback behavior is ambiguous.

## Phase 4 — Rename internal implementation symbols selectively

**Scope**

- Rename internal symbols only where the old name materially harms maintainability.
- Keep compatibility imports or wrappers for public Python APIs.
- Migrate one namespace at a time: imports, environment, files, API, and service names
  must never move in one release.

**Compatibility gate**

- Public API and import contract tests pass for both names.
- Database migration tests prove forward upgrade and rollback.
- EbiBot and at least one clean reference deployment pass real end-to-end checks.

**Rollback**

- Restore the previous internal implementation behind the compatibility facade.
- Do not delete migrated data until the rollback window has closed.

## Phase 5 — Consider legacy retirement

This phase is not authorized by ADR-0001.

Removing `ccdb` or another legacy identifier requires:

- a separate accepted ADR;
- a major-version release;
- a published deprecation window;
- evidence that maintained consumers have migrated;
- explicit data backup and rollback procedures.

The valid outcome may be to retain small aliases permanently when their maintenance cost
is lower than the migration risk.

## Pull request boundaries

Keep review and rollback small:

1. ADR and plan only.
2. Brand documentation and assets.
3. Repository rename and redirect verification.
4. Distribution alias.
5. CLI alias.
6. Configuration aliases.
7. Any internal or persisted identifier, one namespace per PR.

Do not combine deployment topology, Teams implementation, or customer tenant changes
with a rename phase.
