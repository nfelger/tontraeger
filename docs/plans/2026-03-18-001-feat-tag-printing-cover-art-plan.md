---
title: "feat: Add tag printing with cover art"
type: feat
status: completed
date: 2026-03-18
origin: docs/brainstorms/2026-03-16-tag-printing-brainstorm.md
---

# feat: Add Tag Printing with Cover Art

## Overview

Add a print feature to the server web UI that lets users select NFC tag mappings and print a physical sheet of 65×65mm cards — each showing album/playlist/radio artwork — to cut out, laminate, and attach to physical NFC tags.

Server-only feature. No client changes. No new Python dependencies beyond stdlib.

## Problem Statement / Motivation

Physical NFC tags are blank — there's no visual indication of what music they trigger. Users want printed artwork cards to attach to tags so they can identify them at a glance on a shelf.

## Proposed Solution

Three capabilities added to the server:

1. **Artwork capture** — automatic (Spotify oEmbed) and manual ("Capture from Now Playing" + URL paste) flows to fetch and store artwork as base64 in the database
2. **Artwork display** — thumbnails shown on every mapping row, lazy-loaded from a new image endpoint
3. **Print view** — CSS `@page` A4 layout with a 3×4 grid of 65×65mm cards, L-shaped cut guides, ready for browser print dialog

(see brainstorm: `docs/brainstorms/2026-03-16-tag-printing-brainstorm.md`)

## Technical Considerations

### Database

- Add `image_data TEXT NOT NULL DEFAULT ''` column to `tags` table via `ALTER TABLE` with existing swallow-on-error pattern in `_init_db()` (`tag_mapper.py:28`)
- **Critical:** Also add the column to the `CREATE TABLE` DDL (`tag_mapper.py:18-25`) so both agree (see learnings: `docs/solutions/logic-errors/shuffle-feature-review-patterns.md`)
- `get_all_mappings()` excludes `image_data`, adds computed `has_image` boolean — return type changes from `list[tuple[str, str, str, bool]]` to include the new field
- New `get_mappings_with_images(uids: list[str])` returns full image data for print view
- New `upsert_image(tag_uid: str, image_data: str)` stores base64 image
- `content_hash()` must exclude `image_data` — it's server-only and irrelevant to client sync ETag

### HTTP Fetching

No `requests` dependency needed — use `urllib.request` from stdlib to fetch oEmbed JSON and download images. Keep it simple:
- `urllib.request.urlopen(url, timeout=10)` with a short timeout
- Read response bytes, base64-encode, store
- Catch `URLError`/`HTTPError` and fail gracefully (mapping creation succeeds, image stays blank)

### Image Serving

`GET /mappings/<uid>/image` decodes base64 → raw bytes, serves with appropriate `Content-Type`. Detect type from magic bytes (JPEG starts with `\xff\xd8`, PNG with `\x89PNG`), defaulting to `image/jpeg` since most album art is JPEG. Used for `<img src="...">` in both the mapping list (thumbnails) and print view.

### Print Layout

Separate inline template string (like `PAGE_TEMPLATE` in `web.py:65`). CSS-only layout designed for a two-cut lamination workflow:

**Physical workflow:** print → cut paper cards along rounded outline → place in A4 lamination pouch (spaced apart) → laminate → cut laminate with ~2mm sealed border around each card.

**Layout details:**
- `@page { size: A4; margin: 0; }` with `@media print` rules to hide non-card elements
- Grid: 3 columns × 4 rows of 59mm cells, edge-to-edge, centered within printable area (177mm wide, fits within typical ~5mm unprintable margins)
- Printed cards are 59×59mm — leaves 3mm on each side for laminate seal, resulting in 65×65mm final laminated cards
- Each cell shows a rounded outline (59×59mm, `border-radius: 3mm`) — visible at corners and grid perimeter
- Artwork fills the full 59mm card (`object-fit: contain`, `border-radius: 3mm` clip, white background for non-square art)
- First cut: straight lines along row/column boundaries (single cutting motion per line)
- Second cut: freehand through laminate ~3mm outside each paper card

### Alpine.js State

Extend `formHelper()` (`web.py:538`) with:
- `printMode: false` — toggled by "Print tags" / "Cancel" buttons
- `selectedTags: new Set()` — tracks checked UIDs
- Per-row artwork capture logic (reuses existing `selectedSpeaker`)

### Learnings Applied

- Add `image_data` to both `CREATE TABLE` and `ALTER TABLE` (`docs/solutions/logic-errors/shuffle-feature-review-patterns.md`)
- Don't manually `escape()` values in `flash()` calls — trust Jinja2 auto-escaping
- Use dedicated CSS class for checkbox form fields, not generic `.form-field` flex
- `GET /api/mappings` adds `has_image` boolean to the response. The client ignores unknown fields (it only reads `tag_uid`, `media_uri`, `name`, `shuffle`), so this is safe without client-side changes. `image_data` itself is excluded entirely.

## Acceptance Criteria

- [x] `image_data` column added to `tags` table (both DDL and migration)
- [x] Spotify artwork auto-fetched on mapping creation for `https://open.spotify.com/` URIs
- [x] "Capture from Now Playing" button fetches and stores artwork from selected speaker
- [x] Manual URL paste field stores artwork
- [x] Artwork thumbnail shown on every mapping row (placeholder when no image)
- [x] Thumbnails lazy-load via `GET /mappings/<uid>/image`
- [x] `GET /api/mappings` excludes `image_data`, includes `has_image` boolean
- [x] "Print tags" button shows checkboxes; "Cancel" hides them
- [x] Checkboxes disabled/greyed when no artwork captured
- [x] "Print selected" opens print view in new tab
- [x] Print view renders 3×4 grid of 65×65mm cards on A4
- [x] Cards have 3mm rounded corners, `object-fit: contain`, white background
- [x] L-shaped corner tick marks for cut guides
- [x] All new routes have tests
- [x] `make check` passes (lint + typecheck + test)

## Implementation Phases

### Phase 1: Database + Image Storage

**Files:** `tag_mapper.py`, `test_tag_mapper.py`

1. Add `image_data` column to `CREATE TABLE` DDL and `ALTER TABLE` migration
2. Update `get_all_mappings()` to return `has_image` boolean (exclude `image_data` blob)
3. Add `get_mappings_with_images(uids)` method
4. Add `upsert_image(tag_uid, image_data)` method
5. Ensure `content_hash()` excludes `image_data`
6. Tests for all new/changed methods

### Phase 2: Image Fetch + Store Routes

**Files:** `web.py`, `test_web.py`

1. Add helper function to fetch image from URL → base64 (using `urllib.request`)
2. Add helper to fetch Spotify oEmbed → thumbnail URL → image data
3. Extend `POST /mappings` to auto-fetch Spotify artwork on creation
4. Add `POST /mappings/<uid>/image` route (accepts `{"image_url": "..."}`)
5. Add `GET /mappings/<uid>/image` route (serves raw image bytes)
6. Extend `GET /now-playing` response to include `album_art`
7. Update `GET /api/mappings` to include `has_image` field
8. Tests for each route (mock `urllib.request.urlopen`)

### Phase 3: Web UI — Thumbnails + Artwork Capture

**Files:** `web.py` (inline template)

1. Add thumbnail `<img>` to each mapping row (lazy-loaded from `/mappings/<uid>/image`)
2. Add placeholder icon when `has_image` is false
3. Add "Capture" button per row (calls `/now-playing` then `POST /mappings/<uid>/image`)
4. Add manual URL input field per row
5. CSS for thumbnail sizing, placeholder styling, capture controls layout
6. Use dedicated CSS class for capture controls (not generic `.form-field`)

### Phase 4: Web UI — Print Selection Mode

**Files:** `web.py` (inline template)

1. Add "Print tags" button that toggles `printMode` Alpine state
2. Show checkboxes on each row when `printMode` is true
3. Disable/grey checkboxes when `has_image` is false
4. Add "Cancel" button to exit selection mode
5. Add "Print selected" button that opens `/print?tag_uid=...` in new tab
6. CSS for selection mode visual state

### Phase 5: Print View

**Files:** `web.py`

1. Add `GET /print` route accepting `?tag_uid=uid1&tag_uid=uid2&…`
2. Create print template with `@page { size: A4; margin: 0; }` CSS
3. 3×4 grid of 65×65mm cards, edge-to-edge
4. Card images via `<img src="/mappings/<uid>/image">` with `border-radius: 3mm`, `object-fit: contain`, white background
5. L-shaped corner tick marks as cut guides
6. Test: verify route returns HTML with correct images for given UIDs

## Success Metrics

- User can go from mapping creation to printed card sheet in under 2 minutes
- Print output at 100% scale produces correctly-sized 65×65mm cards
- Spotify mappings automatically have artwork without manual intervention

## Dependencies & Risks

| Risk | Mitigation |
|------|------------|
| Spotify oEmbed endpoint changes/rate-limits | Graceful failure — mapping created without image; user can capture manually later |
| SoCo album_art URL is local speaker IP | Server is always on same LAN (confirmed in brainstorm) |
| Non-square artwork looks odd | `object-fit: contain` with white letterboxing |
| Browser print scaling varies | Document "set scale to 100%" in print view instructions |
| `urllib.request` blocks Flask during image fetch | Acceptable — single user, short timeout, infrequent operation |

## Edge Cases

- **Mapping deleted while in print selection** — print view should handle missing UIDs gracefully (skip, don't error)
- **Image fetch timeout/failure** — mapping creation succeeds, `image_data` stays blank, user can retry via Capture or manual URL
- **Very large images** — oEmbed returns ~640px; for manual URLs, consider limiting to reasonable size or just storing as-is (modest mapping count)
- **Duplicate Spotify fetch on mapping update** — `INSERT OR REPLACE` means re-saving a mapping re-fetches; acceptable since it's idempotent
- **Print with 0 tags selected** — disable "Print selected" button when `selectedTags` is empty

## Sources & References

- **Origin brainstorm:** [docs/brainstorms/2026-03-16-tag-printing-brainstorm.md](docs/brainstorms/2026-03-16-tag-printing-brainstorm.md) — key decisions: base64 storage in tags table, lazy-loaded thumbnails with has_image flag, print selection mode with cancel, 3mm rounded corners
- **Learnings:** [docs/solutions/logic-errors/shuffle-feature-review-patterns.md](docs/solutions/logic-errors/shuffle-feature-review-patterns.md) — CREATE TABLE/ALTER TABLE must agree, dedicated CSS classes for form elements
- Server routes: `server/tontraeger_server/web.py`
- Database: `server/tontraeger_server/tag_mapper.py`
- Sonos API: `server/tontraeger_server/sonos_api.py`
- Tests: `server/tests/test_web.py`, `server/tests/test_tag_mapper.py`
- Spotify oEmbed API: `https://developer.spotify.com/documentation/embeds/reference/oembed`
