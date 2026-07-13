# Page and QA checklist

## Home

- Show brand, classification, search, recommended, popular, new goods, contact, and real editorial content.
- Make nursery/product imagery a first-viewport signal and leave the next content band partially visible.
- Remove cart, order, payment, coupon, distribution, supplier, and after-sale entry points.
- Ensure desktop and mobile modules use real ShopXO data or approved configurable sources.

## Category, search, and filters

- Support category, public-price range, height, ground/breast diameter, and origin for P0.
- Keep applied filters visible and removable; preserve sorting for comprehensive, newest, views, favorites, and price.
- Include empty, loading, invalid-filter, and mobile drawer states.
- Do not claim search-event analytics until the analytics task and evidence exist.

## Product list

- Show image, name, summary, public price/unit, main measurements, origin, detail link, and favorite action.
- Keep price and measurement baselines stable across cards; long Chinese species names must wrap without resizing the grid.
- Do not show off-shelf or logically deleted goods to ordinary users.

## Product detail

- Verify gallery, video, reference price, unit, specifications, nursery parameters, origin, nursery information, body, planting, care, transport, and price note.
- Keep favorite and immediate inquiry together without either becoming a prerequisite.
- Check media failure, unavailable specification, off-shelf, anonymous, and logged-in states.

## User and inquiry

- Preserve registration/login and user-data isolation.
- Keep favorites, inquiry history, and replies in separate navigation and data flows.
- Mask personal data outside explicitly authorized views.

## Admin

- Favor compact tables, filters, fixed action columns, explicit status, and append-only history.
- Preserve ShopXO permissions and confirm hidden mall menus are also route/API inaccessible for the target role.
- Do not restyle unrelated admin pages inside a feature task.

## Visual QA matrix

Check at minimum:

- 1440x900 desktop;
- 1024x768 compact desktop/tablet;
- 390x844 mobile;
- 360x800 narrow mobile.

At each size verify no overlap, horizontal overflow, cropped actions, empty image boxes, illegible overlays, layout shifts, or inaccessible focus. Inspect browser console and network failures. Compare screenshots to the approved page brief, not only to the previous ShopXO appearance.
