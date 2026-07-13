# Review checklist

## Product failures

- Price is hidden until login or inquiry, or inquiry reply overwrites public price.
- Favorite creates inquiry, inquiry creates favorite, or either becomes a prerequisite.
- Off-shelf/delete breaks favorite, inquiry, snapshot or statistics history.
- A PX mall route, API, menu or permission remains reachable by target users.

## Authorization and privacy

- Object lookup trusts a request ID without filtering by current user.
- Admin full-phone access lacks a specific permission and audit event.
- Export, logs, events, screenshots or fixtures expose full phone/address/inquiry content.
- Upload validation trusts extension only or stores executable content under a public path.

## Data and state

- Inquiry snapshot reads live product fields when rendering history.
- Status or reply updates overwrite history instead of appending audit rows.
- Favorite uniqueness is only UI-enforced and races can create duplicates.
- Migration lacks idempotency, rollback/forward repair, unique constraints or required indexes.
- `config/shopxo.sql` is changed without a versioned forward migration, or a fresh-install-only exception is claimed without a concrete L4-approved no-existing-instance rationale.
- Product deletion still uses upstream physical-delete behavior without an approved retention design.

## Analytics

- IP is used as the sole UV identity.
- Event retries double count because event IDs are not idempotent.
- Numerator and denominator use different windows or populations.
- Dashboard scans the entire event table instead of daily summaries.
- Search logging duplicates an existing ShopXO table without a migration/compatibility rationale.

## ShopXO integration

- Claimed hook does not exist in the pinned commit or runs after the required mutation.
- Plugin layout is copied from a conceptual document rather than an actual installed example.
- Generic service/core edits are used without documenting why configuration or hooks fail.
- `vendor/**` is edited directly or committed generated changes are mixed with feature code.

## Evidence

- “Passed” has no command, exit code or output.
- Missing PHP/Composer/database/browser is reported as success.
- Scope comparison omits untracked, deleted, renamed or case-variant Windows paths.
- Approval is asserted only from self-editable task fields.
- A required source/control-plane file, task, active state, verify manifest, review pack, executable, cwd, or changed file traverses a symlink or Windows junction.
- Evidence omits any required test's exact `TEST_COMMAND` or `TEST_RESULT: <id> exit_code=0`, or ignores timeout/output-limit/control-plane integrity failures.
