# Brainstorm: Allow Mappings to Be Edited

**Date:** 2026-03-21
**Status:** Ready for planning

## What We're Building

Inline editing of existing mappings in the web UI. Currently, changing any field on a mapping requires deleting it and recreating it from scratch (losing any uploaded artwork in the process). This adds inline edit capability to each mapping card so users can edit all fields and save — without leaving the page.

## Why This Approach

Inline editing fits naturally with the existing htmx-driven UI. It's the lightest-weight option: no new pages, no modals, no navigation. The pattern is familiar and keeps the single-page feel.

Alternatives considered:
- **Edit form/page** — Adds navigation overhead for a simple operation. Overkill.
- **Modal dialog** — Extra UI complexity with no real benefit over inline editing here.

## Design Principles

**Consistency between create and edit:** The new mapping form and the edit mode should offer the same editing capabilities for shared fields. If a field is editable in one place, it should be editable in the other. Convenience features that aren't about editing a specific field (like "Now Playing") belong in neither — they should be standalone tools.

## Key Decisions

1. **Inline editing** — Edit icon per card. Clicking it puts the entire card into edit mode.
2. **Editable fields: name, media_uri, shuffle, image** — All fields except `tag_uid` (primary key). Image upload controls move into edit mode.
3. **No auto-refresh of cover art on URI change** — Changing the media URI does NOT automatically re-fetch Spotify artwork. Users can manually update via the image upload controls in edit mode.
4. **Server-side: update endpoint** — `POST /mappings/<tag_uid>/edit` (or similar) that accepts the updated fields and returns the updated card HTML for htmx swap.

## Interaction Design

### Card Modes

**View mode (default):**
- Card displays data as currently, but with an **edit icon** (pencil) instead of the delete button
- Artwork thumbnail, name, shuffle badge, tag UID, media URI — all read-only
- No image upload controls visible

**Edit mode (click edit icon):**
- All fields become input elements:
  - **Name** — text input
  - **Media URI** — text input
  - **Shuffle** — checkbox (consistent with new mapping form)
  - **Image** — upload controls (file upload + URL fetch), moved here from view mode
- Image uploads save immediately via existing endpoint (not batched with Save)
- **Save** and **Cancel** buttons appear (card-level, not per-field)
- **Delete** button also appears in edit mode (so delete requires: click edit, then click delete)
- Tag UID remains non-editable (primary key)

### Save/Cancel Behavior

- **Save** — POST to server via htmx, server returns updated card HTML, htmx swaps it back to view mode
- **Cancel** — Discard changes, swap back to view mode (no server round-trip needed, htmx or Alpine can handle this client-side)
- **Delete** — Same confirmation dialog as current, then delete

## Out of Scope

- **"Now Playing" button** — Currently lives in the new mapping form but is really a standalone convenience tool for getting a URI. Will be extracted separately (see TODO.md). Not included in edit mode.
- **Image upload on new mapping form** — New mappings auto-fetch Spotify artwork on creation. Adding manual image upload to the create form is a possible future improvement but not needed now.

## Open Questions

None — scope is well-defined.
