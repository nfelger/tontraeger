---
title: "Pure htmx inline editing — server-rendered view/edit card swaps instead of Alpine.js state"
category: ui-bugs
date: 2026-03-21
tags: [htmx, alpine-js, inline-editing, fragment-swap, form-attribute]
components: [server/tontraeger_server/web.py]
---

## Problem

Needed to add inline editing to mapping cards — click Edit, fields become inputs, Save/Cancel/Delete appear. The natural first instinct was Alpine.js `x-data` with an `editing` boolean and stored original values for Cancel revert. This works but adds client-side state management (tracking original values, toggling visibility, handling the Cancel→restore flow).

## Root Cause

Alpine.js is the wrong tool when the server already has all the data. The "toggle between view and edit" pattern is just swapping two HTML fragments — exactly what htmx does.

## Solution

Three endpoints serve card HTML fragments, every transition is a server swap:

- `GET /mappings/<tag_uid>/edit-form` → returns edit mode card (inputs pre-filled)
- `GET /mappings/<tag_uid>/card` → returns view mode card (read-only)
- `POST /mappings/<tag_uid>/edit` → saves, returns view mode card

The Edit button uses `hx-get` to fetch the edit form. Cancel uses `hx-get` to re-fetch the view card. Save uses `hx-post`. All three target the same card element via `hx-target="#card-<css_id>"` with `hx-swap="outerHTML"`.

```python
# Python helpers return card HTML strings (like _thumb_html)
def _card_view_html(tag_uid, media_uri, name, shuffle, has_image) -> str: ...
def _card_edit_html(tag_uid, media_uri, name, shuffle, has_image, error=None) -> str: ...
```

**Key technique — `form` attribute:** Edit mode inputs use `form="edit-form-<css_id>"` to associate with the Save form, even though the inputs aren't inside the `<form>` element. This allows flexible layout (inputs in card body, Save button in footer) without nesting constraints.

**Cancel is a server call**, not client-side revert. This costs a trivial GET request but eliminates all client-side state tracking. The server returns the authoritative view, which is always correct (e.g., if an image was uploaded mid-edit, Cancel shows the new image).

**Validation errors** return 200 with the edit form re-rendered including the error message — htmx ignores non-2xx by default, so always return 200 with appropriate HTML.

## Prevention / Best Practice

**Decision heuristic:** If you're about to add Alpine.js `x-data` to toggle between two visual states, check if htmx `hx-get` + `outerHTML` swap can do it instead. Server-rendered swaps are simpler, have no client-side state to manage, and the server always returns the authoritative view.

Alpine.js is still appropriate for genuinely client-side concerns: reactive UI state (print mode toggle), polling, and interactions that can't round-trip to the server.

## Related

- [htmx form fragment swap for image upload](htmx-form-fragment-swap-for-image-upload.md) — same `outerHTML` swap pattern for mutations
- [htmx CSS selector colons in IDs](htmx-css-selector-colons-in-ids.md) — `css_id` filter required on all dynamic IDs used in `hx-target`
