# CLAUDE.md

Raspberry Pi-based Sonos controller. NFC tags trigger music playback (place tag = play, remove tag = pause). Monorepo with two components: a Flask server for mapping management and a Raspberry Pi client for tag reading + Sonos control.

## Project Structure

```
server/          Flask web UI + JSON API + SQLite (own pyproject.toml, Makefile, uv.lock)
client/          NFC reader + local cache + Sonos playback (own pyproject.toml, Makefile, uv.lock)
  nfc-daemon/    C daemon that talks to PN532 via libnfc, emits PRESENT/REMOVED events
```

Dependencies managed with **uv**.

## Verifying Changes

IMPORTANT: run `/usr/bin/make check` before committing — this runs lint, typecheck, and test across both components.

Single test file: `cd server && uv run pytest tests/test_web.py`
Single test: `cd server && uv run pytest tests/test_web.py::test_add_mapping`
Auto-format: `make format`

Every commit must pass `make check` and include tests for new functionality.

## Architecture Essentials

The critical path (place card, play music) has **no server dependency**. The client cache allows playback to keep working when the server is down or unreachable. Do not introduce server dependencies on the playback path.

Server and client communicate via a JSON API (`GET /api/mappings`, `POST /api/unknown-tags`, `POST /api/media-metadata`). Changes to the API response shape require coordinated updates in both components — the client parses the server's JSON directly in `sync.py` and `cache.py`.

- Spotify share links (`https://`) go through SoCo's `ShareLinkPlugin`; all other URIs use `add_uri_to_queue`.

## Rules & Principles

- **Prefer htmx for server-driven interactions** (data fetching, rendering lists, polling, state transitions). Use htmx server-rendered HTML fragments + swaps as the default for all UI interactions.
- **Use Alpine.js where it's genuinely simpler** than htmx — e.g., client-side DOM manipulation (setting input values), UI mode toggles, multi-state buttons, or reactive state that doesn't need a server round-trip. Alpine.js is a complement to htmx, not a last resort.
- **Use red/green TDD** for new features and bug fixes.

## NFC Reliability Breadcrumbs (Paused)

- Investigation paused after reliability reached acceptable day-to-day behavior.
- Final daemon policy in `client/nfc-daemon/main.c`: treat only `NFC_ETGRELEASED`, `NFC_EINVARG`, and `NFC_EDEVNOTSUPP` as hard misses; treat other negatives (notably `NFC_ERFTRANS`) as transient.
- Most stable transport observed in testing: `pn532_i2c:/dev/i2c-1`.
- Full investigation notes and hypothesis log: `docs/superpowers/plans/2026-04-10-pn532-false-removed-investigation.md`.
- If issues return, resume with targeted diagnostics around the session handoff window (new tag placed before prior session has emitted `REMOVED`).
