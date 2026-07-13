---
name: shopxo-nursery-review
description: Review ShopXO nursery changes against the local task contract, product requirements, open decisions, security and data gates, ShopXO extension boundaries, and truthful verification evidence. Use for code review, diff review, pre-merge audit, core-change review, database review, authorization review, analytics review, or release readiness in this repository.
---

# ShopXO Nursery Review

Review independently from the implementation narrative. Prefer raw task files, diffs, source, test logs and database assertions.

## Establish Scope

1. Read `AGENTS.md`, `.harness/CONSTITUTION.md`, the task contract, and referenced requirements.
2. Use `nursery_harness` MCP `task_get` and `requirement_get` when available.
3. Run `source-check`, `task-check`, `scope-check`, and `evidence-check` for the task.
4. Confirm the pinned ShopXO baseline and inspect actual upstream code around every claimed extension point.

## Review Order

1. Task authorization and changed-path integrity.
2. Business invariants and acceptance scenarios.
3. User ownership, admin permissions, personal-data handling, rate limits and audit trail.
4. Snapshot/history semantics, migrations, idempotency, indexes, rollback and deletion behavior.
5. Event names, sensitive fields, PV/UV/metric formulas and raw-to-summary reconciliation.
6. ShopXO upgrade surface, plugin/hook validity and core-change registration.
7. Tests, exit codes, blocked or unexecuted work, and release/rollback evidence.

Read [review-checklist.md](references/review-checklist.md) for domain-specific failure patterns.

## Output

Lead with actionable findings ordered by severity. For each finding cite the file and tight line range, describe the concrete failure scenario, name the violated requirement or Harness rule, and state the minimum correction. Separate confirmed defects from questions and environmental blockers.

Do not approve because fields such as `reviewer` or `approved_by` are populated. Treat them as evidence to corroborate, not proof of independent approval.

If no defect is found, state residual risks and unverified areas. Do not modify implementation files unless the user also asks to fix findings.

Reject symlinked or junction-backed source/control-plane/task/evidence/report paths, `config/shopxo.sql` as the only existing-site upgrade path, missing per-test evidence markers, output-limit failures, or required tests that changed either business files or the Harness control plane.

Only an independent reviewer may record approval. A separate Codex review agent
may act as reviewer when explicitly authorized by the project owner, but the
implementation agent may not assume that identity. When the review is approved,
write the exact standalone marker `REVIEW_RESULT: APPROVED` in `review.md`, record
the reviewer identity/date, create the fixed `approval-merge.json` matching the
CLI-computed context, then use `task-approval ... merge` with the contracted
agent task. Task/thread fields and the artifact are self-asserted audit context,
not cryptographic proof of identity.

For L4 or any task declaring release approval, corroborate a second approval by
the contracted release agent, who must differ from both owner and reviewer and
must inspect the remote contract, host fingerprint, exact action argv, managed
roots, backup, rollback, shared-service diff, clean release commit/seal, and
latest verification evidence before approving. Reject raw SSH/SCP execution or
mutating broker evidence whose Git commit does not match the release seal.
