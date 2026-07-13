---
name: shopxo-nursery-task
description: Plan, implement, and verify requirement-traceable changes in this repository's ShopXO nursery website. Use for any nursery feature, bug, UI, data, security, analytics, ShopXO plugin, core adaptation, task-contract, implementation-plan, or verification work that may modify project files.
---

# ShopXO Nursery Task

Use the repository Harness as the execution contract. Do not start from remembered ShopXO conventions or from the requirements document alone.

## Start

1. Read `AGENTS.md` and `.harness/CONSTITUTION.md`.
2. Run `python scripts/harness.py doctor` when source or toolchain status is uncertain, and run `source-check` before any business implementation.
3. Identify one task ID and its requirement IDs. Use the `nursery_harness` MCP tools when available; otherwise search the local requirements document with `rg`.
4. Read `.harness/requirements-decisions.json`. Stop implementation when an affected decision is open.
5. Read the task's `task.json`, `requirement.md`, impact analysis, implementation plan, and test plan.

If ShopXO source is incomplete or `app/common.php` is missing, restrict work to discovery, Harness, requirements, or environment repair unless the task explicitly owns that blocker.

## Plan

Inspect the actual pinned ShopXO code before naming services, hooks, plugin paths, tables, or tests. Use this preference order:

```text
configuration → existing service → verified hook → nursery plugin → isolated module → small core adaptation
```

Record why each earlier option is insufficient. Include data migration, rollback, authorization, analytics definitions, upstream-sync impact, and acceptance evidence when relevant.

Read [workflow.md](references/workflow.md) for task states and required artifacts. Read [requirement-routing.md](references/requirement-routing.md) when selecting phase, risk, gates, or tests.

## Implement

1. Require task status `approved_for_implementation`.
2. Run `python scripts/harness.py preflight <TASK_ID>`, then transition to `implementing`.
3. Modify only `allowed_paths`; treat `vendor/**`, production configuration, Harness policy, and unapproved ShopXO core files as protected.
4. Preserve upstream style and avoid unrelated formatting.
5. Keep excluded mall capabilities disabled through configuration, menus, views, routes, and permissions; do not physically delete upstream subsystems merely to hide them.
6. For data changes, provide forward SQL/update logic, rollback or forward-repair strategy, idempotency, indexes, backup notes, and tests against the actual schema. Never use `config/shopxo.sql` as the only upgrade path for an existing site; a fresh-install-only exception requires a concrete contract reason and L4 plan approval.
7. Reject any source, control-plane, task, state, evidence, report, executable, test cwd, or patch path that traverses a symlink or Windows junction.

## Verify

Move the task to `verifying` through `task-transition`, then run the declared checks:

Run the task's declared checks through:

```text
python scripts/harness.py verify <TASK_ID>
python scripts/harness.py scope-check <TASK_ID>
# Fill evidence.md with VERIFY_CONTRACT_SHA256, then one TEST_COMMAND and TEST_RESULT: <id> exit_code=0 line per test; a local timestamped run path is optional.
python scripts/harness.py evidence-check <TASK_ID>
python scripts/harness.py review-pack <TASK_ID>
```

Before `release-check`, complete `release-note.md`. For a task with required
release approval, the recorded `release_approver` must be different from both
the owner and reviewer. These roles may be separate Codex agents when the
project owner has explicitly authorized autonomous approvals; the implementing
agent must not record its own review or release approval. Record merge/release approvals, then transition to
`approved_for_merge`; that transition performs the pre-transition readiness
check. Run standalone `release-check` only after the transition so CLI/CI can
prove the state was not skipped.

Report missing tools or fixtures as `blocked`, and report unexecuted work separately. Never convert a missing PHP, Composer, browser, database, fixture, or service into a pass.

`verify` runs commands without a shell, with offline/sensitive-environment cleanup and bounded stdout/stderr. A timeout, output-limit breach, business-worktree mutation, or Harness/control-plane mutation is a failed verification. If a damaged or stale active state cannot be removed by a normal transition, use the CLI `state-recover` flow; never delete it manually.

## Remote Execution

Run network, SSH, deployment, database initialization, shared-gateway edits, or remote smoke tests only for an L4 operations task with `network_access_required=true` and a locked `remote_execution` contract. Raw SSH/SCP/curl remains prohibited: invoke `remote-actions`, `remote-exec`, `release-seal`, and standalone `release-check` only as `python -I -S -B scripts/harness.py ...` (or through a project wrapper that adds those flags). Use the pinned host fingerprint, external user-SSH file references, managed roots and structured argv. Never read credential or application-secret contents. Before any mutating action, require independent release approval, `approved_for_merge`, a clean committed worktree and `release-seal`. Inventory shared services before changes, preserve pre-change snapshots, validate configuration before reload, and execute only the declared rollback action when a gate fails. Isolated startup prevents repository stdlib shadowing; it is not a platform signature for the Python executable.

The broker's internal release-check launcher must reuse its already verified in-memory broker module through the private script-globals object-identity context. It must not re-read the sibling broker after validation, and no environment variable or argv value may select that trusted path. Direct isolated CLI calls continue to load the exact sibling file.

## Stop Conditions

Stop for an open requirement decision, contract-external remote action, ShopXO core deletion, unresolved user-data access rule, analytics definition change, or destructive migration. L3/L4 approvals may proceed through distinct Codex reviewer/release agents only when the project owner has explicitly authorized that mode and the required evidence is complete. Do not widen the task implicitly.
