# Task workflow

## Artifacts

Each task lives in `.harness/tasks/<TASK_ID>/`:

- `task.json`: machine-readable scope and authorization.
- `workflow-history.json`: CLI-owned state-transition and approval audit events.
- `requirement.md`: requirement excerpts, business goal, exclusions, and open decisions.
- `impact-analysis.md`: affected flows, tables, hooks, callers, security, analytics, upgrade risk.
- `implementation-plan.md`: ordered changes and rollback points.
- `test-plan.md`: named checks, fixtures, expected results and required environment.
- `evidence.md`: actual commands, exit codes, assertions, screenshots and limitations.
- `review.md`: independent findings and approval record.
- `release-note.md`: deployment, migration, rollback and post-release smoke checks.

## Lifecycle

```text
draft
→ ready_for_analysis
→ awaiting_plan_approval
→ approved_for_implementation
→ implementing
→ verifying
→ awaiting_review
→ approved_for_merge
→ closed
```

Use `blocked` or `cancelled` when appropriate. Do not skip approval for L3/L4, database, authorization, analytics-contract, or core-impact work.

Use `python scripts/harness.py task-transition ...` for every state change and
`python scripts/harness.py task-approval ...` for plan, merge, or release decisions.
Do not patch an active `task.json` directly. Open product decisions may remain
warnings during analysis and planning, but they block approval for implementation
and every implementation/review gate.

## Contract integrity

The plan approval event hashes `requirement.md`, `impact-analysis.md`, `implementation-plan.md`, and `test-plan.md`, plus the selected resolved-decision context. Preflight locks those hashes together with task identity, business goal/invariants, owner/reviewer/release approver, priority, phase, risk, requirements, decisions, scope paths, core/data declarations, acceptance definitions, required tests, rollback policy, and plan approval. `evidence.md` is the only acceptance-evidence source; lifecycle status and merge/release approval results are controlled post-preflight fields. Changing any locked field, planning artifact, or selected decision invalidates the active task and requires renewed approval. Per-task locks serialize workflow history updates, and a global active-state lock prevents two tasks from preflighting concurrently.

Do not manually delete a damaged or stale `active-task.json`. First move the task to a recoverable state (`ready_for_analysis`, `awaiting_plan_approval`, `blocked`, `closed`, or `cancelled`), then use `state-recover` with a contracted actor and concrete reason. Add `--allow-invalid-state` only after inspecting malformed JSON, a symlink, or a Windows junction; the CLI retains a local audit record/snapshot.

## Evidence quality

- Preserve each exact command array as `TEST_COMMAND: <id> <argv JSON>` and each successful exit as `TEST_RESULT: <id> exit_code=0`.
- Record the stable `VERIFY_CONTRACT_SHA256` emitted by verify and every required test ID in `evidence.md`; a local timestamped run directory is optional because CI creates a new one.
- Redact passwords, tokens, full phone numbers, addresses and inquiry text.
- Link each acceptance ID to a reproducible assertion.
- Complete `release-note.md` before release readiness. Required release approval must come from the contracted release approver, not the owner or reviewer.
- Mark environmental gaps separately from product failures.
- Keep raw run output local or in expiring CI artifacts; commit only redacted summaries.
- Treat timeout, bounded-output overflow, symlink/junction paths, required-test worktree mutation, or control-plane mutation as verification failure. The code hard-caps each output stream at 1 MiB and each test at 3600 seconds.
