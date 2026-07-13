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
- `approval-plan.json`, `approval-merge.json`, `approval-release.json`: fixed-path JSON attestations for bound Codex approval stages.

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

The v2 task contract always contains `codex_role_bindings`. Legacy/non-automated tasks may keep every binding null only to replay old history; new `task-approval` events require a bound stage. An automated task locks the implementation canonical task/thread and each required approval task before review. The plan context locks contract, policy, four plan artifacts, and decision context. Merge locks review-pack, stable workspace content, evidence, and verify contract. Release additionally locks merge approval, review, release note, and current remote contract; `release-seal` is intentionally created only after approval. Each bound reviewer must create the fixed ordinary JSON artifact, pass the exact bound `--agent-task`, and run under a UUID `CODEX_THREAD_ID` different from implementation. History records and replays expected/observed task/thread, artifact path/canonical SHA, and context SHA. These are self-asserted audit facts, not cryptographic identity proof.

Do not manually delete a damaged or stale `active-task.json`. First move the task to a recoverable state (`ready_for_analysis`, `awaiting_plan_approval`, `blocked`, `closed`, or `cancelled`), then use `state-recover` with a contracted actor and concrete reason. Add `--allow-invalid-state` only after inspecting malformed JSON, a symlink, or a Windows junction; the CLI retains a local audit record/snapshot.

## Evidence quality

- Preserve each exact command array as `TEST_COMMAND: <id> <argv JSON>` and each successful exit as `TEST_RESULT: <id> exit_code=0`.
- Record the stable `VERIFY_CONTRACT_SHA256` emitted by verify and every required test ID in `evidence.md`; a local timestamped run directory is optional because CI creates a new one.
- Redact passwords, tokens, full phone numbers, addresses and inquiry text.
- Link each acceptance ID to a reproducible assertion.
- Complete `release-note.md` before release readiness. Required release approval must come from the contracted independent release role, not the owner or reviewer. Separate Codex agents may fill these roles under explicit project-owner authorization.
- Mark environmental gaps separately from product failures.
- Keep raw run output local or in expiring CI artifacts; commit only redacted summaries.
- Treat timeout, bounded-output overflow, symlink/junction paths, required-test worktree mutation, or control-plane mutation as verification failure. The code hard-caps each output stream at 1 MiB and each test at 3600 seconds.
