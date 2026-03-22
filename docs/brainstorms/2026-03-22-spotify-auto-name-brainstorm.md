# Brainstorm: Auto-populate Tag Name from Spotify Metadata

**Date:** 2026-03-22
**Status:** Draft

## What We're Building

When a user pastes a Spotify share link into the "add mapping" form, automatically fetch the title from Spotify's oEmbed endpoint and fill in the name field — so users don't have to manually type "Kids Playlist" or "Beatles - Abbey Road" when Spotify already knows.

This is the first half of the TODO item "Bulk add share links + pull image and title from Spotify." The bulk-add flow will come later and will build on this auto-name capability.

## Why This Approach

- **oEmbed is already in use** — the server calls Spotify's oEmbed endpoint to fetch artwork on save. The `title` field in that response is currently discarded. We just need to also use it.
- **Client-side fetch on paste** gives immediate feedback — the user sees the name appear as soon as they paste a link, before submitting. More satisfying UX than a server-side fill that only shows after save.
- **Using the oEmbed title as-is** is simplest and most robust. Spotify already formats album titles as "Artist - Album" and playlist titles as just the playlist name, which matches what the TODO asked for.

## Key Decisions

1. **Trigger: client-side on input, general-purpose server endpoint** — A new endpoint (e.g., `POST /api/media-metadata`) accepts any media URL. Server-side, it checks if it's Spotify and returns oEmbed title if so, empty response otherwise. Client just sends every URI change to this endpoint — no Spotify detection in JS.

2. **Only fill blank names** — If the user already typed something in the name field, don't overwrite it. Auto-fill only applies when the name field is empty.

3. **Title only, no artwork preview** — The client-side fetch populates just the name. Artwork continues to be fetched and stored server-side on form submission, as it is today.

4. **Add form only** — No changes to the edit form. Keep scope minimal.

5. **Use oEmbed title as-is** — No parsing or reformatting of the title string. Whatever Spotify returns is what goes in the name field.

## Approach

- Add a general-purpose server endpoint (e.g., `POST /api/media-metadata`) that accepts any media URL. The server checks if it's a Spotify link and returns `{ "title": "..." }` via oEmbed if so; returns empty/null metadata for anything else. This keeps all source-detection logic server-side and makes the endpoint extensible to other sources later.
- On the add form, listen for changes to the media URI field. On any change (debounced), POST the URL to the metadata endpoint and set the name field value from the response (if name is blank).
- Client-side JS has no knowledge of Spotify — it just asks the server "do you have metadata for this URL?" This simplifies the client and avoids duplicating URL detection logic.

## Open Questions

None — scope is well-defined and narrow.
