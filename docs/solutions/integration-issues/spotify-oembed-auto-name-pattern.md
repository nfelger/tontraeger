---
title: Auto-populate form fields from Spotify oEmbed metadata
category: integration-issues
date: 2026-03-22
tags: [spotify, oembed, alpine-js, api-endpoint, auto-fill, debounce]
module: server/tontraeger_server/web.py
---

# Auto-populate form fields from Spotify oEmbed metadata

## Problem

Users had to manually type tag names when adding Spotify mappings, even though Spotify already knows the title (playlist name, "Artist - Album", etc.). The server was already calling Spotify's oEmbed endpoint for artwork but discarding the `title` field.

## Root Cause

The original `fetch_spotify_artwork()` fetched the full oEmbed response but only extracted `thumbnail_url`, throwing away the rest of the metadata including `title`.

## Solution

### 1. Extract `fetch_spotify_oembed()` helper

Refactored `fetch_spotify_artwork()` into two functions: a lower-level `fetch_spotify_oembed()` that returns the full oEmbed dict, and `fetch_spotify_artwork()` as a thin wrapper.

```python
def fetch_spotify_oembed(spotify_url: str) -> dict[str, Any] | None:
    """Fetches oEmbed metadata for a Spotify URL (title, thumbnail, etc.)."""
    oembed_url = f"https://open.spotify.com/oembed?url={quote(spotify_url, safe='')}"
    try:
        req = Request(oembed_url, headers={"User-Agent": "tontraeger/1.0"})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read(16384))  # cap at 16KB
    except (URLError, OSError, ValueError, KeyError):
        return None

def fetch_spotify_artwork(spotify_url: str) -> str | None:
    data = fetch_spotify_oembed(spotify_url)
    if data:
        thumbnail_url = data.get("thumbnail_url")
        if thumbnail_url:
            return fetch_image_as_base64(thumbnail_url)
    return None
```

### 2. General-purpose media metadata endpoint

`POST /api/media-metadata` accepts any URL, returns `{"title": "..."}` for Spotify, `{"title": null}` otherwise. All source-detection logic lives server-side — the client has no knowledge of Spotify.

```python
@app.route("/api/media-metadata", methods=["POST"])
def media_metadata() -> Response:
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

### 3. Alpine.js auto-fill with debounce and user-override tracking

Key design decisions:
- **`nameAutoFilled` flag** distinguishes user-typed names (never overwritten) from auto-filled names (overwritten when URL changes). The flag resets via `@input="nameAutoFilled = false"` on the name input.
- **400ms debounce** via `setTimeout`/`clearTimeout` prevents firing on every keystroke.
- **`fetchNowPlaying()` calls `fetchMetadata()` directly** because programmatic `.value` assignment does NOT fire DOM `input` events — a common gotcha.
- **Double-check in `fetchMetadata`** is intentional: the early return checks state before the `await`, the guard before assignment re-checks after, because the user could type during the async gap.

## Prevention / Best Practices

- **When calling external APIs, extract all useful data** — don't discard fields you might need later. Returning the full response from a helper function is more reusable than extracting a single field.
- **General-purpose endpoints over source-specific ones** — `POST /api/media-metadata` can be extended to other music services without client changes.
- **Programmatic `.value =` doesn't fire input events** — always trigger fetches explicitly after programmatic value changes in Alpine.js/vanilla JS.
- **Track auto-filled vs user-typed state** when auto-populating form fields that users can also edit manually.
