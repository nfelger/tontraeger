---
title: Add Shuffle Flag to Tag Mappings
type: feat
status: completed
date: 2026-03-16
origin: docs/brainstorms/2026-03-16-spotify-radio-shuffle-brainstorm.md
---

# feat: Add Shuffle Flag to Tag Mappings

## Overview

Add a `shuffle: bool` field to NFC tag mappings so that placing a tag can start Sonos in shuffle mode. The field is stored in the server DB, exposed via the JSON API, synced to the client cache, and applied at playback time via a SoCo `play_mode` call. When `shuffle=False`, play mode is explicitly reset to `NORMAL` to prevent bleed from a previous shuffle tag.

## Problem Statement / Motivation

Users want to assign NFC tags to Spotify Radio experiences — dynamically generated playlists seeded from a song, artist, or album. Placing the tag should feel fresh on every listen: random order, continuous playback. Without a per-tag shuffle setting, users must either manually toggle shuffle on the speaker (which bleeds between tags) or accept a fixed playback order.

The shuffle flag is also generally useful for any static playlist the user wants played in random order.

## Proposed Solution

Add one boolean column (`shuffle`) to the `tags` table and propagate it through every layer:

1. **Server DB** — `ALTER TABLE ... ADD COLUMN shuffle INTEGER NOT NULL DEFAULT 0` migration (existing pattern in `_init_db`)
2. **Server API** — include `"shuffle": bool(s)` in `/api/mappings` JSON objects
3. **Server web UI** — add a "Shuffle" checkbox to the "New Mapping" form; show a visual indicator on mapping cards
4. **Client `cache.py`** — parse `shuffle` from JSON (`m["shuffle"]`); expand in-memory tuple; add `get_shuffle()` accessor; persist to disk
5. **Client `control.py`** — fetch shuffle from cache in `handle_present`, pass to `sonos_api.play_uri`
6. **Client `sonos_api.py`** — accept `shuffle: bool = False` in `play_uri` / `_do_play`; call `coordinator.play_mode = "SHUFFLE" if shuffle else "NORMAL"` after `clear_queue`, before `add_uri_to_queue`

(See brainstorm: docs/brainstorms/2026-03-16-spotify-radio-shuffle-brainstorm.md)

## Technical Considerations

### Play Mode Ordering

Set `coordinator.play_mode` **after `clear_queue` and before `add_uri_to_queue`**. Sonos firmware applies the play mode to the entire queue lifecycle; setting it before any tracks are added ensures the mode is active when `play_from_queue(0)` fires. The updated `_do_play` sequence:

```python
# client/tontraeger_client/sonos_api.py
def _do_play(self, uri: str, shuffle: bool = False) -> None:
    coordinator = self._speaker.group.coordinator
    coordinator.clear_queue()
    coordinator.play_mode = "SHUFFLE" if shuffle else "NORMAL"   # NEW
    if uri.startswith("https://"):
        ShareLinkPlugin(coordinator).add_share_link_to_queue(uri)
    else:
        coordinator.add_uri_to_queue(uri)
    coordinator.play_from_queue(0)
```

### SoCo Play Mode Values

Use `"SHUFFLE"` (shuffle + repeat all) for `shuffle=True`. This gives the standard "radio" feel. `"SHUFFLE_NOREPEAT"` is explicitly rejected — the brainstorm decision is shuffle + repeat. The mode string should be a module-level constant: `PLAY_MODE_SHUFFLE = "SHUFFLE"` and `PLAY_MODE_NORMAL = "NORMAL"`.

### Interface: `play_uri(uri, shuffle)`

The shuffle flag is a parameter on `play_uri`, not a separate pre-call. This keeps the Sonos API surface clean and avoids ordering bugs. `DummySonosAPI` in `test_control.py` must be updated to accept the new parameter.

### Error Handling for `set_play_mode`

If `coordinator.play_mode = ...` raises a SoCo / UPnP exception, treat it identically to all other SoCo errors in `sonos_api.py`: set `_speaker = None` and re-raise. The error will bubble up through `play_uri` and `handle_present`, logging an error. The caller already handles this path.

### ETag Invalidation

`content_hash()` in `tag_mapper.py` (lines 90–97) currently serializes only `tag_uid`, `media_uri`, and `name`. It **must include `shuffle`** — toggling shuffle on a mapping must change the ETag so the client receives a `200` rather than `304` and picks up the change.

### Schema Migration

Follow the existing pattern at `tag_mapper.py:26–30`:

```python
# server/tontraeger_server/tag_mapper.py
try:
    cursor.execute(
        "ALTER TABLE tags ADD COLUMN shuffle INTEGER NOT NULL DEFAULT 0"
    )
except sqlite3.OperationalError:
    pass
```

### Cache Tuple Expansion

`MappingCache._mappings` expands from `dict[str, tuple[str, str]]` to `dict[str, tuple[str, str, bool]]`. All internal accesses (`get_uri`, `get_name`, `_persist`, `all_mappings`) need updating. New `get_shuffle(tag_uid) -> bool` accessor returns `False` if the tag is not in the cache.

### No Edit UI

Changing shuffle on an existing mapping requires delete-and-recreate in the web UI. This is the accepted UX for now. Adding inline-edit is out of scope.

### "Now Playing" Capture

The "Now Playing" flow does **not** pre-populate the shuffle checkbox. The user must check it manually. Pre-populating from the current Sonos play mode is out of scope.

## System-Wide Impact

- **Critical path**: Shuffle is read from the local cache at playback time. No server call is made during playback. The critical path (NFC → cache → Sonos) remains fully server-free. ✅
- **API versioning**: The new `shuffle` field is additive. Old clients that don't know about `shuffle` will ignore it; no breaking change. Old server responses (without `shuffle`) are handled by `m.get("shuffle", False)` in the client. ✅
- **ETag / 304**: `content_hash` must include `shuffle` or toggling it will be silently invisible to the client.
- **Existing mappings**: All existing tags default to `shuffle=False` (DB `DEFAULT 0`). No migration of data needed, only schema.
- **Cache file compatibility**: Not required. The client cache will be wiped and repopulated from the server on first sync after deployment.

## Acceptance Criteria

- [x] New mapping created with "Shuffle" checked → `shuffle=True` in DB and API response
- [x] New mapping created without "Shuffle" → `shuffle=False` in DB and API response
- [x] Existing mappings in DB (pre-migration) load correctly with `shuffle=False`
- [x] Placing a shuffle=True tag sets Sonos play mode to `SHUFFLE` before queue is populated
- [x] Placing a shuffle=False tag sets Sonos play mode to `NORMAL` (bleed prevention)
- [x] Placing a shuffle=True tag after a shuffle=False tag plays in shuffle mode
- [x] Placing a shuffle=False tag after a shuffle=True tag plays in normal mode
- [x] `content_hash()` changes when shuffle is toggled on a mapping
- [x] Client poll receives updated shuffle value after server-side change
- [x] Mapping cards in the web UI show a visual shuffle indicator for shuffle=True tags
- [x] `make check` passes (lint, typecheck, tests)

## Open Questions

- **URI compatibility for Spotify Radio**: When Spotify radio is cast to Sonos, the URI returned by `get_current_track_info()` may or may not be replayable via `add_uri_to_queue` or `ShareLinkPlugin`. This must be validated manually during implementation before launch. It does not block the shuffle feature itself — if the URI is not replayable, that is a separate issue from the shuffle flag.

## Dependencies & Risks

- **SoCo `play_mode` API**: The `coordinator.play_mode` property is well-established in SoCo. No version risk identified.
- **Sonos firmware behaviour**: Mode must be set before `play_from_queue(0)`. If firmware applies the mode asynchronously, there could be a brief window where the first track plays in the wrong order. Setting mode before `add_uri_to_queue` minimises this window.
- **Test suite coupling**: Several tests assert the exact tuple shape of cache entries. These will all need updating — they are a source of friction but not risk.

## Sources & References

- **Origin brainstorm:** [docs/brainstorms/2026-03-16-spotify-radio-shuffle-brainstorm.md](../brainstorms/2026-03-16-spotify-radio-shuffle-brainstorm.md) — Key decisions carried forward: shuffle flag on mappings (not Spotify API), SHUFFLE mode (shuffle + repeat), explicit NORMAL reset on shuffle=False.

### Internal References

- Tag mapper DB + migration pattern: `server/tontraeger_server/tag_mapper.py:18–30`
- `content_hash` that needs shuffle: `server/tontraeger_server/tag_mapper.py:90–97`
- API response shape: `server/tontraeger_server/web.py:634–646`
- Page template + mapping form: `server/tontraeger_server/web.py:66` (inline template)
- Mapping card loop: `server/tontraeger_server/web.py:473–495`
- `add_mapping` route: `server/tontraeger_server/web.py:602–610`
- Cache parse + in-memory structure: `client/tontraeger_client/cache.py:21–29`
- Cache persist: `client/tontraeger_client/cache.py:71–73`
- Playback dispatch: `client/tontraeger_client/control.py:39–51`
- `_do_play` sequence: `client/tontraeger_client/sonos_api.py:31–43`
- `play_uri` async wrapper: `client/tontraeger_client/sonos_api.py:56–70`
- `DummySonosAPI` fake: `client/tests/test_control.py:14`
- Server API mapping test: `server/tests/test_web.py:186–194`
