# Brainstorm: Physical Tag Printing with Cover Art

**Date:** 2026-03-16
**Status:** Ready for planning

---

## What We're Building

A print feature in the server web UI that lets users select NFC tag mappings and print a physical sheet of cards — each showing the album/playlist/radio artwork — to cut out and attach to physical NFC tags.

The feature lives entirely on the server side and is UI-only (no client/playback path changes needed).

---

## User Flow

1. User clicks a "Print tags" button in the mapping list
2. Checkboxes appear on each row (hidden until this point to reduce visual clutter)
3. User checks the mappings they want to print
4. User clicks "Print selected" → opens a print view in a new browser tab
5. The print view shows a grid of cards with cover art and a rounded 65×65mm cut outline per card
6. User hits Ctrl+P, sets scale to 100%, prints on A4
7. User cuts paper cards along rounded outline, places in lamination pouch, laminates, cuts laminate with ~2mm border

**Artwork capture flow (one-time, per mapping):**
- **Spotify URIs**: Server auto-fetches artwork from Spotify's public oEmbed endpoint (`https://open.spotify.com/oembed?url=…`) during `POST /mappings`, downloads the image, and stores it as base64 in `image_data`. No credentials needed; returns a ~640×640 px thumbnail (~250 DPI at 65mm — acceptable quality for shelf cards). If the fetch fails, mapping creation still succeeds with blank `image_data`.
- **Sonos radio / other URIs**: A "Capture from Now Playing" button on each mapping row. User plays the station on a Sonos speaker, selects the speaker in the existing "Now Playing" speaker dropdown, then clicks the button. The server fetches the `album_art` URL from SoCo's `get_current_track_info()`, downloads the image, and stores it as base64 in `image_data`. Note: SoCo may return a local Sonos speaker URL (e.g. `http://192.168.x.x:1400/...`) for some content types — this is best-effort and only works from devices on the same LAN as the speaker.

---

## Why This Approach

- **Browser print with CSS mm layout** — no new Python dependencies. `@page { size: A4; }` with `mm` units is reliable when print scale is set to 100%. This is how browser-based invoice/label tools work.
- **Spotify oEmbed** — public API, no credentials, one HTTP call during mapping creation. Covers the most common use case automatically.
- **SoCo Now Playing** — SoCo already fetches `album_art` alongside the URI in `get_current_track_info()`. Extending the existing `/now-playing` route costs nothing extra.
- **Stored image data in DB** — artwork fetched and stored as base64-encoded image data per mapping. Avoids issues with external URLs expiring or being inaccessible at print time; images are always available for printing even if the original source goes offline.
- **Two-cut lamination workflow** — cards printed on A4 with spacing, each showing a rounded 65×65mm cut outline. User cuts out paper cards along the outline, places them spaced apart in an A4 lamination pouch, laminates, then cuts the laminate ~2mm outside each card for sealed edges. Only the rounded outline needs precision; the rest is rough cutting.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Print format | Sheet of selected tags | User picks which ones to reprint |
| Card content | Cover art only, full bleed, slightly rounded corners (3mm radius) | Clean, minimal — rounded corners look nicer and are more durable after lamination; CSS `border-radius: 3mm` on card images, cut guides remain L-shaped tick marks |
| Card size | 59×59mm printed, 65×65mm laminated | Printed card is 59mm to leave 3mm laminate seal on each side; fits 12 cards on A4 in a 3×4 grid |
| Paper size | A4 | Standard |
| Card spacing | Edge-to-edge (no gap) | Single straight cut separates whole row/column; rounded outline visible at corners and grid perimeter |
| Cut guides | Solid rounded outline (65×65mm, 3mm radius) | Single precision cut line per card; laminate cut is freehand |
| Image fit | `object-fit: contain` with white background | Letterbox for non-square artwork; Spotify art is square so mostly full-fill |
| Image quality | ~250 DPI (640px) | Acceptable for decorative shelf cards |
| Lamination | Print → cut paper cards → place in pouch → laminate → cut laminate | Two-cut workflow: precision cut along rounded outline, then freehand ~2mm border through laminate for sealed edges |
| Spotify artwork | oEmbed thumbnail (auto, no creds) | Covers the dominant use case without credentials |
| Radio artwork | "Capture from Now Playing" button | Works for any Sonos content; leverages existing SoCo call |
| Manual override | URL paste field alongside Capture button | Fallback for any content type |
| No-artwork checkbox | Greyed out / disabled | Must capture artwork before a tag is selectable for print |
| Capture UX | Immediate save, re-click overwrites | No preview step; no separate clear button needed |
| Image storage | `image_data` column in `tags` table (base64) | Persisted per mapping; blank until captured; never sent to client sync endpoint |
| Print rendering | Browser print + CSS mm | No new dependencies; reliable for simple square cards |

---

## Implementation Scope (Server Only)

### Database
- Add `image_data TEXT NOT NULL DEFAULT ''` column to `tags` table (base64-encoded image) using the existing `ALTER TABLE` / swallow-on-error migration pattern in `TagMapper._init_db()`
- Two getter methods: `get_all_mappings()` excludes `image_data` but includes a `has_image` boolean (lightweight, used by list view and client sync); `get_mappings_with_images(uids)` includes `image_data` (used by print view)

- `GET /api/mappings` (client sync endpoint) never includes `image_data` — images are server-only, not needed for playback

### New / Extended Routes
- `POST /mappings` — auto-fetch oEmbed thumbnail when URI starts with `https://open.spotify.com/`; store as `image_data`
- `POST /mappings/<uid>/image` — accepts an image URL, fetches the image, stores as base64 in `image_data` (used by "Capture from Now Playing" and manual URL input flows)
- `GET /mappings/<uid>/image` — returns raw image bytes with appropriate `Content-Type` header (used for lazy-loading thumbnails via `<img src="...">` and for the print view)
- `GET /now-playing?speaker=X` — extend response to include `album_art` (already available from SoCo, just not surfaced)
- `GET /print` — accepts `?tag_uid=uid1&tag_uid=uid2&…`; renders the CSS mm print sheet

### Web UI Changes
- "Print tags" button enters selection mode: checkboxes appear on each mapping row (Alpine.js state); **greyed out and disabled** when `image_data` is blank. Checkboxes hidden until user enters this mode, reducing visual clutter. A **Cancel** button exits selection mode.
- "Print selected" button (visible in selection mode) → opens `/print?tag_uid=…` in new tab
- Each mapping row **always** shows a small artwork thumbnail (when image exists) or a placeholder icon (when blank) — visible outside print mode too, giving visual feedback that artwork is captured. Thumbnails loaded lazily via `GET /mappings/<uid>/image`; `get_all_mappings()` returns a `has_image` boolean flag.
- Artwork controls shown together in each row:
  - **"Capture" button** → uses the speaker selected in the "Now Playing" dropdown, calls `/now-playing`, immediately saves the returned `album_art` via `POST /mappings/<uid>/image` (no preview step; re-clicking overwrites)
  - **Manual URL input** → a text field in the same area for pasting an image URL directly, submitted via the same `POST /mappings/<uid>/image` route

### Client Impact
- `image_data` is excluded from `GET /api/mappings` — it's a server-only field not needed for playback. No client changes required.

---

## Resolved Questions

- **250 DPI at 65mm acceptable?** Yes — fine for decorative shelf cards at normal viewing distance.
- **CSS mm reliable for physical sizing?** Yes, when print dialog is at 100% scale and paper is set to A4.
- **Spotify credentials needed?** No — oEmbed is a public endpoint.
- **Lamination workflow?** Print → cut paper cards along rounded outline → place spaced in A4 lamination pouch → laminate → cut laminate ~2mm outside each card. Two precision cuts per card (paper + laminate), sealed edges on all sides.
- **Image fit for non-square artwork?** `object-fit: contain` with white background (letterbox). Spotify art is square so mostly fills the card.
- **No-artwork behavior?** Checkbox greyed out and disabled; must capture artwork first.
- **Capture UX?** Save immediately on click; re-clicking overwrites. No preview, no clear button.
- **Server on same LAN as speakers?** Yes, always — local Sonos album art URLs will resolve fine.
- **DB size with base64 images?** Not a concern — mapping count stays modest, SQLite handles it fine.
- **Exit selection mode?** Cancel button alongside "Print selected" to exit without printing.
- **Thumbnails always visible?** Yes — always shown in mapping rows, not just in print mode. Loaded lazily via `GET /mappings/<uid>/image` with a `has_image` flag in the listing.

---

## Open Questions

_(none)_
