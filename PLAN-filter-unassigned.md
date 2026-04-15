# Plan: Filter Unassigned Mappings

## Summary

Add a client-side toggle button to filter the mapping list to only show items with no tag assigned. Uses a CSS class on the container + `data-unassigned` attribute on cards for O(1) filtering. Composes cleanly with print mode. Server embeds counts at render time so the badge updates without DOM counting.

## Tasks

### 1. Write tests for the filter feature (TDD — red phase)

File: `server/tests/test_web.py`

- **Test: index page includes unassigned count in Alpine store init** — Create 3 mappings (2 with tag, 1 without). GET `/`. Assert the rendered HTML contains `totalCount: 3` and `unassignedCount: 1` in the Alpine store initialization.
- **Test: card view HTML includes `data-unassigned` for unassigned mapping** — Create a mapping without `tag_uid`. GET `/mappings/<id>/card`. Assert `data-unassigned` is present in the response.
- **Test: card view HTML does NOT include `data-unassigned` for assigned mapping** — Create a mapping with `tag_uid`. GET `/mappings/<id>/card`. Assert `data-unassigned` is absent.
- **Test: index page renders filter toggle button** — GET `/` with some mappings. Assert the "Show unassigned" button text is present in the response.

### 2. Add `data-unassigned` attribute to card HTML

File: `server/tontraeger_server/web.py`, function `_card_view_html()` (~line 1262)

When `tag_uid is None`, add `data-unassigned` to the card's outer `<div class="card" ...>`:
- `<div class="card" id="card-{mapping_id}" x-data>` → `<div class="card" id="card-{mapping_id}" data-unassigned x-data>` (conditionally).

### 3. Add CSS rule for filtering

File: `server/tontraeger_server/web.py`, CSS section (~after line 488)

```css
.filter-unassigned .card:not([data-unassigned]) { display: none; }
```

### 4. Add Alpine store for filter state + embed server counts

File: `server/tontraeger_server/web.py`

a) Alpine store init (~line 836): Add a `filter` store with `unassigned: false`, `totalCount` and `unassignedCount` (templated from server).

b) `index()` route (~line 1053): Compute `unassigned_count = sum(1 for m in mappings if m.tag_uid is None)` and pass both counts to the template.

### 5. Add filter toggle button to toolbar

File: `server/tontraeger_server/web.py`, template (~lines 804-819)

Add a toggle button before "Print tags" that toggles `$store.filter.unassigned` and adds/removes the `filter-unassigned` CSS class on `#card-list`.

### 6. Update badge count to reflect filter state

File: `server/tontraeger_server/web.py`, template (~line 803)

Replace the static `{{ mappings|length }}` badge with an Alpine-reactive span that shows `unassignedCount of totalCount` when filtering, or just `totalCount` otherwise. Keep `{{ mappings|length }}` as fallback before Alpine initializes.

### 7. Add `id="card-list"` to the card container

File: `server/tontraeger_server/web.py`, template (~line 800)

Add `id="card-list"` to the outer div wrapping the card loop so the CSS class toggle has a target.

### 8. Run `make check`, fix any issues

## Not in scope

- No server-side filtering or new routes
- No changes to the API (`/api/mappings`)
- No changes to the client component
- No changes to the print route or print template
- No additional filter dimensions (just unassigned yes/no)

## Risks / edge cases

- **Print mode + filter**: Independent toggles. Selections persist when filter is toggled because they live in a separate Alpine store.
- **Edit while filtered**: htmx swaps target `#card-{id}` which works regardless of filter state. A card that gains a tag via edit will remain visible until filter is re-toggled (acceptable).
- **Empty filtered state**: Badge showing "0 of 12" makes it clear the filter is active; no special empty-state message needed.
