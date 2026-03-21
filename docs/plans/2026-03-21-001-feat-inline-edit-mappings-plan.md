---
title: "feat: Inline edit mappings"
type: feat
status: completed
date: 2026-03-21
origin: docs/brainstorms/2026-03-21-edit-mappings-brainstorm.md
---

# feat: Inline Edit Mappings

## Overview

Add inline editing to mapping cards. Currently, editing requires deleting and recreating a mapping (losing artwork). This adds an edit icon per card that toggles all fields into edit mode with Save/Cancel/Delete actions.

## Proposed Solution

Pure htmx approach — every card transition is a server-rendered HTML swap. No Alpine.js state management.

Three endpoints serve card fragments:
- `GET /mappings/<tag_uid>/card` → view mode card HTML
- `GET /mappings/<tag_uid>/edit-form` → edit mode card HTML (inputs pre-filled)
- `POST /mappings/<tag_uid>/edit` → save changes, return view mode card HTML

**View mode (default):** Read-only card with edit icon (pencil) replacing the delete button.
**Edit mode:** Click edit icon → `hx-get` fetches edit form → `hx-swap="outerHTML"`. Shows name (text input), media_uri (text input), shuffle (checkbox), image upload controls. Save, Cancel, Delete buttons. Tag UID displayed as read-only text.
**Save:** htmx `POST /mappings/<tag_uid>/edit` → server returns view mode card HTML → swaps back.
**Cancel:** htmx `GET /mappings/<tag_uid>/card` → server returns view mode card HTML → swaps back. (Server call, but trivial and keeps things pure htmx.)
**Delete:** Same confirmation dialog as today, accessible from edit mode only.
**Image upload:** Saves immediately via existing endpoint (independent of Save/Cancel lifecycle).

## Technical Considerations

### Card HTML extraction

The card markup currently lives inline in `PAGE_TEMPLATE` inside a Jinja `for` loop. To return card fragments from endpoints, extract into two helpers:
- `_card_view_html(tag_uid, media_uri, name, shuffle, has_image)` → view mode
- `_card_edit_html(tag_uid, media_uri, name, shuffle, has_image)` → edit mode with pre-filled inputs

The template loop calls `_card_view_html` for each mapping.

### CSS ID for htmx targeting

Each card needs a unique `id` using the `css_id` filter: `id="card-{{ tag_uid|css_id }}"`. All three endpoints must return fragments with the same ID convention. (See `docs/solutions/ui-bugs/htmx-css-selector-colons-in-ids.md`.)

### Error handling on Save

Return 200 with the card in edit mode + error message if validation fails (e.g., empty media_uri). htmx ignores non-2xx responses by default, so always return 200 with appropriate HTML.

### Print mode interaction

Hide edit icon when print mode is active (Alpine `x-show="!$store.printMode.active"` — this is one of the cases where Alpine is still needed for client-side reactive state).

### Image upload target consistency

The existing image upload uses `hx-target="#thumb-<css_id>"`. Both view and edit mode card fragments must include an element with this ID so image uploads work in edit mode. The edit mode template should show the current thumbnail alongside the upload controls.

### Cancel does not undo image uploads

If a user uploads a new image during edit mode then clicks Cancel, the image change persists (it was already saved server-side). Only text field and shuffle changes are reverted by Cancel. This is intentional — image uploads are a separate operation.

### No artwork auto-fetch on URI change

Explicitly decided in brainstorm: changing media_uri does NOT trigger Spotify artwork fetch. User can manually update via image controls in edit mode.

## Acceptance Criteria

- [x] Each mapping card shows an edit icon (pencil) in place of the delete button
- [x] Clicking edit icon fetches edit form via htmx GET, swaps card to edit mode
- [x] Edit mode shows inputs for name, media_uri, shuffle, plus image upload controls
- [x] Image uploads save immediately via existing endpoint
- [x] Save posts to `POST /mappings/<tag_uid>/edit`, returns view mode card HTML, swaps via htmx
- [x] Cancel fetches view mode card via htmx GET, swaps back (no Alpine state needed)
- [x] Delete is accessible from edit mode with confirmation dialog
- [x] Tag UID is displayed but not editable
- [x] Validation error on Save (empty media_uri) returns edit mode card with error message
- [x] Multiple cards can be in edit mode simultaneously
- [x] Edit icon hidden during print mode
- [x] Edit mode cards render correctly at the existing `@media (max-width: 500px)` breakpoint
- [x] Tests cover: edit form GET, save with valid data, save with empty media_uri, cancel re-fetches view card, delete from edit mode, htmx fragment responses

## MVP

### `server/tontraeger_server/tag_mapper.py`

No changes needed — `insert_mapping` already does upserts and preserves `image_data`.

### `server/tontraeger_server/web.py`

1. Extract card view HTML into `_card_view_html(tag_uid, media_uri, name, shuffle, has_image)` helper
2. Create `_card_edit_html(tag_uid, media_uri, name, shuffle, has_image, error=None)` helper for edit form
3. Update `PAGE_TEMPLATE` to call `_card_view_html` in the mappings loop
4. Add `GET /mappings/<tag_uid>/edit-form` route → returns `_card_edit_html(...)`
5. Add `GET /mappings/<tag_uid>/card` route → returns `_card_view_html(...)`
6. Add `POST /mappings/<tag_uid>/edit` route:
   - Accept `name`, `media_uri`, `shuffle` from form data
   - Validate `media_uri` non-empty; on failure return `_card_edit_html(..., error="...")`
   - Call `mapper.insert_mapping(tag_uid, media_uri, name, shuffle)`
   - Return `_card_view_html(...)` for htmx, or redirect for non-htmx
7. Card view template includes:
   - `id="card-{{ tag_uid|css_id }}"` on card element
   - Edit icon with `hx-get="/mappings/<tag_uid>/edit-form"`, `hx-target="#card-<css_id>"`, `hx-swap="outerHTML"`
   - Print mode: `x-show="!$store.printMode.active"` on edit icon
8. Card edit template includes:
   - Same `id` as view mode
   - Pre-filled inputs for name, media_uri, shuffle checkbox
   - Image upload controls (file + URL, same as current)
   - Save: `hx-post`, `hx-target`, `hx-swap="outerHTML"`
   - Cancel: `hx-get="/mappings/<tag_uid>/card"`, `hx-target`, `hx-swap="outerHTML"`
   - Delete: form with `confirm()`, same as current

### `server/tests/test_web.py`

- `test_edit_form_get` — returns edit mode HTML with pre-filled values
- `test_card_get` — returns view mode HTML
- `test_edit_mapping` — save with valid data, verify view mode card returned
- `test_edit_mapping_empty_uri` — returns edit mode card with error
- `test_edit_mapping_nonexistent` — 404 or appropriate error
- `test_edit_mapping_preserves_image` — image_data unchanged after edit

## Sources

- **Origin brainstorm:** [docs/brainstorms/2026-03-21-edit-mappings-brainstorm.md](docs/brainstorms/2026-03-21-edit-mappings-brainstorm.md) — key decisions: inline editing with edit icon per card, all fields editable except tag_uid, no artwork auto-refresh on URI change, image upload saves immediately
- **Institutional learning:** [docs/solutions/ui-bugs/htmx-css-selector-colons-in-ids.md](docs/solutions/ui-bugs/htmx-css-selector-colons-in-ids.md) — must use `css_id` filter on all dynamic IDs
- **Institutional learning:** [docs/solutions/ui-bugs/htmx-form-fragment-swap-for-image-upload.md](docs/solutions/ui-bugs/htmx-form-fragment-swap-for-image-upload.md) — fragment swap pattern for mutations
- **Existing patterns:** `_thumb_html()` in `web.py:959` — model for card HTML helpers
