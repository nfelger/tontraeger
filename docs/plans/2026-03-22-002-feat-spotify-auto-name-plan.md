---
title: "feat: Auto-populate tag name from Spotify metadata"
type: feat
status: completed
date: 2026-03-22
origin: docs/brainstorms/2026-03-22-spotify-auto-name-brainstorm.md
---

# feat: Auto-populate tag name from Spotify metadata

## Overview

When a user enters a Spotify share link in the add-mapping form, automatically fetch the title from Spotify's oEmbed endpoint and fill the name field — saving manual typing. The oEmbed `title` field is already available (the server calls oEmbed for artwork) but currently discarded. (See brainstorm: docs/brainstorms/2026-03-22-spotify-auto-name-brainstorm.md)

## Proposed Solution

A general-purpose `POST /api/media-metadata` endpoint accepts any media URL and returns metadata if available. Currently only Spotify URLs resolve (via oEmbed); everything else returns `{"title": null}`. The client calls this endpoint on media URI input changes, keeping all source-detection logic server-side.

## Acceptance Criteria

- [x] New `POST /api/media-metadata` endpoint accepts `{"url": "..."}`, returns `{"title": "..."}` for Spotify URLs, `{"title": null}` otherwise
- [x] Pasting a Spotify link into the media URI field on the add form auto-fills the name field (if blank)
- [x] Clicking "Now Playing" when it returns a Spotify URI also triggers the auto-fill
- [x] User-typed names are never overwritten; auto-filled names ARE overwritten when the URL changes
- [x] Non-URL input (`STOP`, Sonos URIs) returns `{"title": null}` without attempting network calls
- [x] Requests are debounced (~400ms) to avoid firing on every keystroke
- [x] Tests cover: Spotify URL returns title, non-Spotify URL returns null, non-URL input returns null, oEmbed failure returns null

## Implementation

### Server: extract `fetch_spotify_oembed()` helper

Refactor `fetch_spotify_artwork()` (web.py:81) to extract a lower-level `fetch_spotify_oembed(url) -> dict | None` that returns the full oEmbed response. `fetch_spotify_artwork()` becomes a thin wrapper that extracts `thumbnail_url` from it.

### Server: `POST /api/media-metadata` endpoint

```python
# web.py
@app.route("/api/media-metadata", methods=["POST"])
def media_metadata():
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    if not url.startswith(("http://", "https://")):
        return jsonify(title=None)
    if url.startswith("https://open.spotify.com/"):
        oembed = fetch_spotify_oembed(url)
        if oembed:
            return jsonify(title=oembed.get("title"))
    return jsonify(title=None)
```

Timeout: use the same timeout as the existing artwork fetch (10s server-side; the client-side UX concern is handled by debounce + the user can submit without waiting).

### Client: Alpine.js in `formHelper()`

Add `x-ref="name"` to the name input. Extend `formHelper()` with:

- A `nameAutoFilled` boolean flag (tracks whether current name was set by auto-fill, so it can be overwritten on URL change)
- A `fetchMetadata(url)` method that POSTs to `/api/media-metadata`, sets `$refs.name.value` if the name is blank or was auto-filled
- Debounce via `setTimeout`/`clearTimeout` in the method
- Wire up via `@input.debounce` on the media URI input (or manual debounce in the method)

The "Now Playing" flow (`fetchNowPlaying()`) should call `fetchMetadata()` after setting the media URI value, since programmatic `.value` assignment does not fire DOM input events.

### Key edge case: auto-filled name on URL change

Track whether the name was auto-filled with a boolean flag. When the user types in the name field, clear the flag. When auto-fill sets the name, set the flag. On subsequent URL changes, overwrite the name only if the flag is set or the field is blank.

```
# web.py - name input
<input type="text" id="name" name="name" x-ref="name"
       @input="nameAutoFilled = false"
       placeholder="e.g. Kids playlist">
```

### Files to modify

- `server/tontraeger_server/web.py` — new endpoint, refactored oEmbed helper, `x-ref` on name input, extended `formHelper()`
- `server/tests/test_web.py` — tests for the new endpoint and auto-fill behavior

### Files NOT modified

- No client/ changes (this is purely a server UI feature)
- No edit form changes (add form only, per brainstorm)
- No database schema changes

## Sources

- **Origin brainstorm:** [docs/brainstorms/2026-03-22-spotify-auto-name-brainstorm.md](docs/brainstorms/2026-03-22-spotify-auto-name-brainstorm.md) — key decisions: general-purpose endpoint, only fill blank names, oEmbed title as-is, add form only
- **Existing pattern:** `fetchNowPlaying()` in `formHelper()` (web.py:818) — same fetch-and-set-input pattern
- **Existing code:** `fetch_spotify_artwork()` (web.py:81) — oEmbed call to refactor
- **Institutional learning:** Alpine.js is the right tool for client-side DOM manipulation / setting input values (docs/solutions/ui-bugs/alpine-to-htmx-migration-pattern.md)
