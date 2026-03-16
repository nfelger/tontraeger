# Brainstorm: Spotify Radio / Shuffle Playback

**Date:** 2026-03-16
**Status:** Draft

---

## What We're Building

A way to assign NFC tags to Spotify "radio" experiences — playlists seeded from a song, artist, or album that Spotify generates and then keeps extending — so that placing the tag starts playback in shuffle mode, giving a fresh feel each time.

The user's workflow: start Spotify radio in the Spotify app, cast it to Sonos, use the "Now Playing" button to capture the playlist URI, check a "Shuffle" checkbox, assign it to an NFC tag.

---

## Why This Approach

### What We Considered

1. **Shuffle flag on mappings** ✅ — Add one boolean field. At playback, set Sonos's play mode before starting. Minimal change, no new dependencies, critical path stays server-free.

2. **Spotify API seed-based recommendations** — Store a seed ID and call Spotify's Recommendations API at playback time for true freshness. Requires OAuth, token management, and server dependencies on the playback path — violates a core architectural constraint.

3. **Try the existing flow as-is** — Test whether "Now Playing" capture already returns a reusable URI. Likely works, but shuffle must be set manually on the speaker and would bleed into other tags.

### Why We Chose the Shuffle Flag

- Fits the YAGNI principle: one field, one SoCo call
- "Feels fresh" (random order) is sufficient; true regeneration adds disproportionate complexity
- Keeps the critical path (NFC → cache → Sonos) completely server-free
- The shuffle flag is general-purpose and useful for static playlists too (bonus)
- Always resets play mode to the mapping's intent — prevents bleed between tags

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Where shuffle lives | Mapping model (`shuffle: bool`) | Persistent, per-tag, synced to client cache |
| Default value | `False` | Non-breaking; existing mappings unaffected |
| Play mode on shuffle=False | Explicitly set `NORMAL` | Prevents bleed if previous tag used shuffle |
| Play mode on shuffle=True | `SHUFFLE` (Sonos: shuffle + repeat) | Standard "radio" feel |
| URI source for radio | "Now Playing" capture (existing UI) | No new UI needed for discovery |
| Spotify API | Not used | Avoids OAuth, server dependency, token management |

---

## Scope

**In scope:**
- Add `shuffle: bool` field to server's tag mapping model (DB + API)
- Add `shuffle` to client's cache/sync parsing
- Update playback logic in both client and server `sonos_api.py`
- Add "Shuffle" checkbox to server web UI
- Tests for the new field and playback behavior

**Out of scope:**
- Spotify API integration
- True per-play regeneration of tracks
- Support for other play modes (repeat, etc.)

---

## Open Questions

- **URI compatibility:** When Spotify radio is cast to Sonos, what URI does `get_current_track_info()` return? Is it replayable via `add_uri_to_queue` or `ShareLinkPlugin`? To be validated during implementation.

