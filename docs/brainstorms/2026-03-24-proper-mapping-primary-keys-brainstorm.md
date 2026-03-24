# Brainstorm: Proper Primary Keys for Mappings

**Date:** 2026-03-24
**Status:** Ready for planning

---

## What We're Building

Replace `tag_uid` as the primary key of the `tags` table with a proper integer surrogate key (`id`). Make `tag_uid` a nullable, editable, unique field. Add an "Assign tag" button in the edit form that uses tap-to-assign: the user clicks it, taps a physical NFC tag, and the UID auto-populates via htmx polling.

### Motivation

Mappings are created before physical tokens are printed and programmed. The current schema forces a tag UID to exist from the start, making it impossible to pre-create mappings and assign tags later. Adding a surrogate PK decouples identity from hardware assignment.

---

## Why This Approach

**Schema + tap-to-assign (Approach B):** Solves the immediate problem (pre-creating mappings) while also providing the UX needed to assign tags efficiently. The existing `/api/unknown-tags` POST mechanism already exists on the client side, so the server-side extension for polling is low-effort. Alpine.js managing the "waiting" state is the natural fit given the project's htmx-first + Alpine-where-simpler principle.

---

## Key Decisions

### Database schema
- Add `id INTEGER PRIMARY KEY AUTOINCREMENT` to the `tags` table
- Change `tag_uid` from `TEXT PRIMARY KEY` to `TEXT UNIQUE` (nullable — no `NOT NULL`)
- Migration: SQLite doesn't support adding a PK column; use the table-recreation pattern (create `tags_new`, copy data, drop old, rename)
- Client API (`GET /api/mappings`) only includes mappings with a non-null `tag_uid` — client playback path is unaffected

### URL routing
- All per-mapping routes change from `/mappings/<tag_uid>/...` to `/mappings/<id>/...`
- CSS element IDs and Alpine.js print selection state switch from `tag_uid` to `id`

### Add form — UID now optional
- Tag UID becomes an optional field on the add form
- A mapping can be created with just a name + media URI — no tag required
- Tap-to-assign (below) is also available on the add form

### Edit form — UID field
- Currently: disabled `<input>` with no `name`, never submitted
- After: enabled `<input name="tag_uid">`, submitted on save
- Duplicate UID: server-side unique constraint violation → return an error response, field stays empty (warn and reject)

### Tap-to-assign
- "Assign tag" button in edit mode
- Click → Alpine.js sets "waiting" state (button label changes, shows spinner/indicator)
- htmx starts polling `GET /api/pending-tag?since=<iso_timestamp>` (timestamp captured at button click)
- Client scans an unknown tag → `POST /api/unknown-tags` (existing mechanism) — `UnknownTagInbox` already stores UIDs with `first_seen`/`last_seen` timestamps in memory
- Poll returns the UID once one arrives after `since` → fills the UID input, Alpine exits "waiting" state, polling stops
- If the returned UID is already assigned to another mapping: server returns a conflict indicator, form shows an error, field stays empty

### Unassigned mappings in the list
- Always visible in the main mapping list
- Visual indicator (e.g., "No tag" badge or greyed-out UID area) to distinguish unassigned from assigned

---

## What's Not Changing

- Client `cache.py`, `sync.py`, `control.py` — no changes needed; playback path is unaffected
- The `/api/mappings` API shape — still returns `tag_uid` per mapping, just only for mappings where it's set
- The client's `POST /api/unknown-tags` mechanism — reused as-is for tap-to-assign

---

## Implementation Scope

- DB migration (table recreation) + `TagMapper` method updates
- URL routes rekeyed from `<tag_uid>` to `<id>`
- Add form: tag UID becomes optional
- Edit form: tag UID becomes editable + "Assign tag" button with polling
- `UnknownTagInbox` already stores UIDs with timestamps — add a polling endpoint
- Alpine.js print selection switches to `id`
- Update all tests + add new ones for nullable UID, UID edit, duplicate rejection, polling

---

## Open Questions

_None remaining — all key decisions resolved._

---

## Resolved Questions

- **Tap assignment mechanism**: polling on button click (not always-on polling, not SSE)
- **Unassigned in list**: always visible with a visual indicator
- **Duplicate UID on assign**: warn and reject (unique constraint, no overwrite)
- **Client impact**: none — only non-null UIDs synced to client
