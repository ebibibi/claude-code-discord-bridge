---
type: adr
id: ADR-0002
title: Gate session completion on owner PR lifecycle
decision: Opt-in deployments resume an agent once when its non-draft session branch still has an open PR in an owner repository.
status: accepted
date: 2026-08-06
deciders: [Masahiko Ebi, Codex]
scope: repository
supersedes:
superseded_by:
---

# ADR-0002: Gate session completion on owner PR lifecycle

## Context

An agent completed a cross-repository naming correction, opened an owner PR with all
checks passing, and then reported the merge as a human follow-up. The PR remained open
for eleven days. The installed plugin therefore retained the old instructions and
recreated the data layout that the session had just corrected.

The existing controls were advisory:

- repository instructions said that owner PRs must be merged;
- a daily brief displayed open public PRs among unrelated items;
- a repository-specific watcher notified on changed PR metadata.

None of those controls bound the PR lifecycle to the Discord session that created it.
The runtime accepted a terminal answer even though the session's conventional branch
still had a ready PR.

## Options considered

### Rely on stronger prompt instructions

Rejected as the only control. The instruction already existed and the failure still
occurred. Prompt rules remain useful, but they are not a completion invariant.

### Auto-merge every green owner PR in the bridge process

Rejected. A green check does not prove that a merge is authorized for every task, and a
bridge-side merge would bypass the agent's repository-specific deployment and
post-merge verification responsibilities.

### Use a daily stale-PR scanner

Rejected as the primary control because detection may be delayed and unrelated old PRs
produce noise. It remains a useful backstop but does not prevent a false completion.

### Resume the same session once for its own open PRs

Accepted. The branch convention `session/<thread_id>` provides a deterministic link
between a Discord session and its PRs without a new database. The same agent retains the
task context needed to wait for checks, fix failures, merge, and verify consumers.

## Decision

1. The gate is opt-in through `CCDB_PR_COMPLETION_OWNER` and disabled by default.
2. At the terminal path, the bridge searches that owner's repositories for non-draft,
   open PRs whose head branch exactly equals `session/<thread_id>`.
3. When matches exist, the bridge resumes the same backend session with a completion
   contract that requires checks, merge, closure verification, and applicable
   post-merge deployment or consumer updates.
4. The automatic continuation happens at most once per user turn. A genuinely blocked
   PR must produce a concrete blocker report instead of an infinite retry loop.
5. GitHub lookup failures fail open so an external outage cannot suppress the agent's
   answer. The bridge posts a visible warning and records the exception.
6. Draft PRs are excluded because draft status explicitly represents intentionally
   incomplete work that may be awaiting user direction.

## Rationale

This design enforces the exact missing invariant while leaving repository decisions to
the agent that has the relevant context. It is narrow enough to avoid acting on other
contributors' PRs or unrelated branches, and the opt-in owner boundary makes the
behavior safe for a general-purpose public bridge.

One continuation is a deliberate circuit breaker. The normal path can complete a green
owner PR automatically, while conflicts, review requirements, failed checks outside the
task scope, or missing authority remain visible to the user rather than consuming turns
forever.

## Consequences and trade-offs

### Positive

- A ready owner PR can no longer be silently delegated back to the user as “done.”
- The check works across repositories without maintaining a repository inventory.
- The agent performs repository-specific post-merge verification instead of a blind
  merge bot.
- GitHub outages degrade visibly without breaking ordinary chat.

### Negative

- Enabled deployments require an authenticated `gh` CLI and one GitHub query at the end
  of eligible turns.
- Branches that do not follow `session/<thread_id>` are outside this invariant.
- A PR still open after the one continuation is reported rather than retried forever.

## Related

- [Issue #577](https://github.com/ebibibi/claude-code-discord-bridge/issues/577)
- [Ebi Workspace PR #9](https://github.com/ebibibi/ebi-workspace/pull/9)
