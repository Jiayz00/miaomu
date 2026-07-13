---
name: shopxo-nursery-ui
description: Design, implement, and visually verify the ShopXO nursery platform interface in this repository. Use for homepage, category, search, filter, goods list/detail, user center, favorites, inquiry, admin nursery screens, responsive styling, theme assets, template changes, or UI review.
---

# ShopXO Nursery UI

Build a specific visual identity for a single-operator nursery catalog and inquiry platform while preserving verified ShopXO routes, data, templates, and accessibility.

## Start

1. Read `AGENTS.md`, `.harness/CONSTITUTION.md`, the active task contract, and its approved plan.
2. Inspect the actual ShopXO template, CSS, JavaScript, hook, and data paths before proposing changes.
3. Read [design-system.md](references/design-system.md) before choosing colors, type, layout, imagery, or components.
4. Read [page-checklist.md](references/page-checklist.md) for the page being changed and its required states.
5. Stop when `source-check` or task `preflight` is not green; UI work is business implementation, not a Harness bootstrap exception.

## Design

Define a compact page brief before coding:

- Name the page's user, primary job, required requirement IDs, and real data it must expose.
- Select one signature nursery element from the design system; do not stack decorative motifs.
- Sketch desktop and mobile information order. Preserve a visible hint of the next section on home-page viewports.
- Identify every ShopXO commerce control that must be hidden or disabled for PX scope.
- Prefer bright, inspectable product and nursery media. Do not use generic lifestyle stock, dark overlays, decorative gradients, or generated SVG illustrations as primary evidence.

Critique the brief once: remove any choice that could belong unchanged to a generic tea, furniture, SaaS, or farm template.

## Implement

1. Work with the existing ThinkPHP/ShopXO view and static-asset stack; do not migrate frameworks.
2. Reuse existing data and actions before adding template conditionals, hooks, plugin views, or isolated assets.
3. Keep public reference price visible in list and detail views. Present favorite and inquiry as independent peer actions.
4. Disable excluded mall capabilities through configuration, navigation, templates, routes, and permissions; do not physically delete upstream core services or tables.
5. Use semantic HTML, visible focus states, reduced-motion handling, descriptive image alternatives, and stable responsive dimensions.
6. Keep product information dense enough for comparison: species, key measurements, origin, unit, availability, and price must scan before decorative copy.
7. Avoid nested cards, pill-heavy controls, oversized marketing type inside compact surfaces, and border radii above 8px unless an existing ShopXO control requires it.

## Verify

1. Run the task's declared checks through the Harness.
2. Exercise the real page at desktop and mobile widths with the project browser workflow.
3. Capture screenshots for home, list, detail, empty/loading/error states, and any modified account or admin flow.
4. Check console errors, broken media, keyboard focus, longest Chinese labels, price/spec alignment, and fixed/mobile navigation.
5. Prove cart, order, payment, coupon, distribution, supplier, and after-sale entry points are absent or inaccessible for target users.
6. Record actual commands, exit codes, screenshot paths, limitations, and acceptance IDs in task evidence.

Use [design-sources.md](references/design-sources.md) only when maintaining this Skill or evaluating upstream design guidance.
