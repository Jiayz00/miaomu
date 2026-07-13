# Requirement routing

Record the selected `PRIORITY` and `PHASE`, plus the source rationale, in
`requirement.md`. The Harness checks that those markers match `task.json`, but
does not infer routing truth from prose automatically. A conflict or ambiguous
cross-phase requirement must be resolved in `.harness/requirements-decisions.json`
and approved by a reviewer before implementation.

## Phase routing

1. ShopXO baseline, menu reduction, nursery taxonomy, product presentation and public price.
2. Registration, user center, favorites, ownership and off-shelf behavior.
3. Inquiry snapshot, submission, admin handling, reply history, state and anti-duplication.
4. Visitor/session identity, event collection, search and daily aggregation.
5. Operational dashboards, reconciliation, ranking and approved exports.
6. Price history, favorite-price changes, retention/channel analysis, notification and alerting.

Do not let a later P1 enhancement block an earlier P0 milestone unless an approved decision explicitly changes the dependency.

## Risk routing

- `L0`: documentation only.
- `L1`: text, style or reversible view configuration.
- `L2`: normal feature/service/API behavior.
- `L3`: user authorization, inquiry state, price history, analytics semantics, personal-data export or schema change.
- `L4`: authentication foundation, framework/core infrastructure, production deployment or destructive data operation.

## Mandatory gates

- Public price: list/detail visibility, valid-price publish check, disclaimer, specification consistency.
- Favorites: uniqueness, ownership, no inquiry side effect, off-shelf retention.
- Inquiry: no favorite prerequisite, immutable snapshot, state/reply history, IDOR, duplicate rule.
- Analytics: event allow-list, visitor/user association, sensitive-field scan, PV/UV formulas, raw/daily reconciliation.
- Upload: extension, MIME, size/count, randomized name and executable-file rejection.
- PX scope: verify hidden/inaccessible entry points and permissions; do not fail because upstream source still exists.
