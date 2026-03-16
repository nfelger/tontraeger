# Brainstorm: Physical Tag Printing with Cover Art

**Date:** 2026-03-16
**Status:** Ready for planning

---

## What We're Building

A print feature in the server web UI that lets users select NFC tag mappings and print a physical sheet of cards — each showing the album/playlist/radio artwork — to cut out and attach to physical NFC tags.

The feature lives entirely on the server side and is UI-only (no client/playback path changes needed).

---

## User Flow

1. User sees the mapping list with checkboxes on each row
2. User checks the mappings they want to print
3. User clicks "Print selected" → opens a print view in a new browser tab
4. The print view shows a grid of 65×65mm cards with cover art and dashed cutting guides
5. User hits Ctrl+P, sets scale to 100%, prints on A4

**Artwork capture flow (one-time, per mapping):**
- **Spotify URIs**: Server auto-fetches artwork from Spotify's public oEmbed endpoint (`https://open.spotify.com/oembed?url=…`) during `POST /mappings`. No credentials needed; returns a ~640×640 px thumbnail (~250 DPI at 65mm — acceptable quality for shelf cards). If the fetch fails, mapping creation still succeeds with a blank `image_url`.
- **Sonos radio / other URIs**: A "Capture from Now Playing" button on each mapping row. User plays the station on a Sonos speaker, selects the speaker in the existing "Now Playing" speaker dropdown, then clicks the button. The server fetches `album_art` from SoCo's `get_current_track_info()` and stores it. Note: SoCo may return a local Sonos speaker URL (e.g. `http://192.168.x.x:1400/...`) for some content types — this is best-effort and only works from devices on the same LAN as the speaker.

---

## Why This Approach

- **Browser print with CSS mm layout** — no new Python dependencies. `@page { size: A4; }` with `mm` units is reliable when print scale is set to 100%. This is how browser-based invoice/label tools work.
- **Spotify oEmbed** — public API, no credentials, one HTTP call during mapping creation. Covers the most common use case automatically.
- **SoCo Now Playing** — SoCo already fetches `album_art` alongside the URI in `get_current_track_info()`. Extending the existing `/now-playing` route costs nothing extra.
- **Stored image URL in DB** — artwork URL stored per mapping; print works offline (images fetched from CDN at print time, not from the Flask server).
- **Full-sheet lamination workflow** — cards printed edge-to-edge, full-bleed; user laminates the A4 sheet first, then cuts through laminate with a rotary cutter. L-shaped corner tick marks guide cuts. No gaps between cards needed.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Print format | Sheet of selected tags | User picks which ones to reprint |
| Card content | Cover art only, full bleed | Clean, minimal — no text cluttering the visual |
| Card size | 65×65 mm | User-specified; fits 12 cards on A4 in a 3×4 grid (leaves ~7.5mm side margins — tight but workable) |
| Paper size | A4 | Standard |
| Card spacing | Edge-to-edge (no gap) | Reduces cutting work; lamination applied to full sheet first |
| Cut guides | Corner tick marks (L-shaped) | Minimal ink, easy to align a ruler |
| Image fit | `object-fit: contain` with white background | Letterbox for non-square artwork; Spotify art is square so mostly full-fill |
| Image quality | ~250 DPI (640px) | Acceptable for decorative shelf cards |
| Lamination | Full sheet → laminate → cut through laminate | Roll/pouch laminator on A4, then rotary cutter; clean sealed edges |
| Spotify artwork | oEmbed thumbnail (auto, no creds) | Covers the dominant use case without credentials |
| Radio artwork | "Capture from Now Playing" button | Works for any Sonos content; leverages existing SoCo call |
| Manual override | URL paste field alongside Capture button | Fallback for any content type |
| No-artwork checkbox | Greyed out / disabled | Must capture artwork before a tag is selectable for print |
| Capture UX | Immediate save, re-click overwrites | No preview step; no separate clear button needed |
| Image storage | `image_url` column in `tags` table | Persisted per mapping; blank until captured |
| Print rendering | Browser print + CSS mm | No new dependencies; reliable for simple square cards |

---

## Implementation Scope (Server Only)

### Database
- Add `image_url TEXT NOT NULL DEFAULT ''` to `tags` table using the existing `ALTER TABLE` / swallow-on-error migration pattern in `TagMapper._init_db()`
- Update `insert_mapping()` and `get_all_mappings()` to include `image_url`

### New / Extended Routes
- `POST /mappings` — auto-fetch oEmbed thumbnail when URI starts with `https://open.spotify.com/`; store as `image_url`
- `POST /mappings/<uid>/image` — accepts `{"image_url": "..."}` to store a captured artwork URL (used by "Capture from Now Playing" flow)
- `GET /now-playing?speaker=X` — extend response to include `album_art` (already available from SoCo, just not surfaced)
- `GET /print` — accepts `?tag_uid=uid1&tag_uid=uid2&…`; renders the CSS mm print sheet

### Web UI Changes
- Add checkbox to each mapping row (Alpine.js state); **greyed out and disabled** when `image_url` is blank
- "Print selected" button → opens `/print?tag_uid=…` in new tab
- Each mapping row shows a small artwork thumbnail (when `image_url` is set) or a placeholder icon (when blank)
- Artwork controls shown together in each row:
  - **"Capture" button** → uses the speaker selected in the "Now Playing" dropdown, calls `/now-playing`, immediately saves the returned `album_art` via `POST /mappings/<uid>/image` (no preview step; re-clicking overwrites)
  - **Manual URL input** → a text field in the same area for pasting an image URL directly, submitted via the same `POST /mappings/<uid>/image` route

### Client Impact
- `image_url` is **not** added to `GET /api/mappings` — it's a UI-only field not needed for playback. No client changes required.

---

## Resolved Questions

- **250 DPI at 65mm acceptable?** Yes — fine for decorative shelf cards at normal viewing distance.
- **CSS mm reliable for physical sizing?** Yes, when print dialog is at 100% scale and paper is set to A4.
- **Spotify credentials needed?** No — oEmbed is a public endpoint.
- **Lamination workflow?** Full A4 sheet → laminate → cut through laminate with rotary cutter. Full-bleed image, edge-to-edge cards, corner tick marks as cut guides.
- **Image fit for non-square artwork?** `object-fit: contain` with white background (letterbox). Spotify art is square so mostly fills the card.
- **No-artwork behavior?** Checkbox greyed out and disabled; must capture artwork first.
- **Capture UX?** Save immediately on click; re-clicking overwrites. No preview, no clear button.

---

## Open Questions

_(none)_
