# Nursery interface design system

## Direction

Use a working nursery field-ledger aesthetic: real specimen photography, precise measurement labels, restrained botanical color, and quiet operational controls. The interface should feel knowledgeable and practical rather than pastoral, luxury-cosmetic, or generic eco-themed.

The signature element is a specimen tag: a narrow structured strip containing the species or item code, two or three key measurements, origin, and availability. Use it on product media or directly below the product name, never as decoration without data.

## Color

Define tokens once and reuse them:

| Token | Value | Role |
|---|---|---|
| `ink` | `#17201B` | Primary text and strong controls |
| `canopy` | `#245B43` | Brand and primary action |
| `leaf` | `#5F825F` | Secondary status and selected filters |
| `mineral` | `#2E6578` | Information, links, and cool contrast |
| `pollen` | `#C89A32` | Small price or attention accent only |
| `mist` | `#F4F7F3` | Page background |
| `paper` | `#FFFFFF` | Reading and tool surfaces |
| `line` | `#D9E1DA` | Dividers and input boundaries |

Do not use a green gradient. Keep `pollen` below roughly 10 percent of a viewport and do not let the palette become green-on-green; text remains `ink`, surfaces remain `mist`/`paper`, and `mineral` provides the second hue family.

## Typography

- Display or editorial species name: `STZhongsong`, `Songti SC`, `Noto Serif SC`, serif.
- Body and controls: `PingFang SC`, `Microsoft YaHei`, `Noto Sans CJK SC`, sans-serif.
- Measurements, prices, codes, and analytics: `DIN Alternate`, `Roboto Mono`, monospace with tabular figures.

Use the serif only for true page identity, species names, and occasional section headings. Use compact sans-serif headings inside filters, cards, user-center panels, and admin tools. Keep letter spacing at zero.

## Layout

- Content width: `min(100% - 32px, 1320px)` on desktop, 16px page gutters on mobile.
- Use 12-column desktop and 4-column mobile grids where ShopXO markup permits.
- Product lists favor stable image ratios and aligned data rows over equal-height marketing cards.
- Use 4px, 8px, 12px, 16px, 24px, 32px, 48px, and 72px spacing steps.
- Keep card radii at 4-8px; inputs and tool buttons use 4px unless inherited controls require otherwise.
- Use borders or background contrast before shadows. If a shadow is necessary, tint it toward `ink` and keep it subtle.

## Components

- Product card: visible media, name, specimen tag, public price/unit, origin, availability, favorite icon, and detail link.
- Price: never hidden behind inquiry. Show fixed, range, starting, or specification price truthfully with a short reference-price note on detail pages.
- Primary actions: `立即询价` and `收藏` are peer actions; inquiry may be primary, but neither creates or requires the other.
- Filters: use checkboxes, selects, segmented controls, and numeric ranges. On mobile use a controlled drawer with a persistent applied-filter count.
- Status: use text plus icon or shape, not color alone. Do not use rounded text pills for ordinary metadata.
- Empty states: name the missing content and offer the next valid action without feature explanations.
- Admin surfaces: preserve dense ShopXO workflows, reduce decorative styling, and optimize scanning, comparison, and repeated action.

## Media

Use real, well-lit nursery stock, specimen close-ups, scale references, and uncropped full-plant views. Preserve the actual product state; avoid blurry atmospheric imagery and heavy color overlays. Product cards use a consistent ratio, while detail galleries may mix overview and detail ratios without shifting controls.

## Motion

Use one restrained home-page entrance sequence and small transform/opacity feedback for interactive elements. Respect `prefers-reduced-motion`. Do not use parallax, smooth-scroll hijacking, ambient orbs, or animation that delays product inspection.
