# CLAUDE.md

Raspberry Pi-based Sonos controller. RFID tags trigger music playback. Monorepo with two components: a Flask server for mapping management and a Raspberry Pi client for tag reading + Sonos control.

## Project Structure

```
server/tontraeger_server/   Flask web UI + JSON API + SQLite storage
server/tests/               Server tests (pytest)
client/tontraeger_client/   RFID reader + local cache + Sonos playback
client/tests/               Client tests (pytest, pytest-asyncio)
```

Each component has its own `pyproject.toml`, `Makefile`, and `uv.lock`. Dependencies managed with **uv**.

## Verifying Changes

```bash
make check                  # IMPORTANT: run this before committing (lint + typecheck + test)
make test                   # all tests
make test-server            # server tests only
make test-client            # client tests only
make lint                   # ruff check
make format                 # ruff format
make typecheck              # mypy
```

Single test file: `cd server && uv run pytest tests/test_web.py`
Single test: `cd server && uv run pytest tests/test_web.py::test_add_mapping`

## Architecture Essentials

The critical path (tap card, play music) has **no server dependency**. The client uses a local cache for O(1) lookup and plays directly on Sonos. The server only manages mappings via the web UI.

- **Server**: Single-process Flask on port 5000. SQLite source of truth. ETag (SHA-256 content hash) for conditional sync.
- **Client**: Polls `GET /api/mappings` every 10s with `If-None-Match`. In-memory dict backed by `mappings.json` on disk. 5-second debounce on duplicate tag reads. asyncio event loop with signal handling.
- `"STOP"` is a special `media_uri` value that pauses playback instead of playing.
- Spotify share links (`https://`) go through SoCo's `ShareLinkPlugin`; all other URIs use `add_uri_to_queue`.

## Key Files

**Server** (`server/tontraeger_server/`):
- `web.py` — All Flask routes, HTML template (single inline string with Alpine.js + htmx), `UnknownTagInbox`
- `tag_mapper.py` — SQLite CRUD + SHA-256 content hash for ETag
- `sonos_api.py` — Speaker discovery via `soco.discover()` and playback control

**Client** (`client/tontraeger_client/`):
- `main.py` — Entry point: wires components, asyncio event loop, signal handlers
- `control.py` — `PlaybackController` (tag lookup + play/stop) and `main_loop` (RFID reading with debounce)
- `cache.py` — `MappingCache`: in-memory dict + atomic JSON persistence (temp file + `os.replace`)
- `sync.py` — `MappingSync`: polls server with ETag, reports unknown tags (fire-and-forget)
- `rfid_reader.py` — MFRC522 hardware interface (SPI/GPIO)

## Things That Will Bite You

- **Conditional import**: `rfid_reader.py` is imported inside `main()` in `client/main.py` to avoid importing `RPi.GPIO` on non-Pi machines. Do not move to a top-level import.
- **Inline HTML template**: The entire UI is a single `PAGE_TEMPLATE` string in `web.py`, not a separate template file. Keep it that way.
- **Schema migration**: `TagMapper._init_db()` runs `ALTER TABLE` and catches the error if the column exists. This is intentional backward compatibility, not a bug.
- **Module-level state in web.py**: `mapper`, `sonos`, and `unknown_tags` are module-level objects. Server tests patch these directly (see `test_web.py` fixtures). Follow this pattern.
- **Client test fakes**: Client tests use simple fakes like `DummySonosAPI` rather than `unittest.mock`. Follow this pattern for new client tests.
- **Platform-guarded deps**: `mfrc522` and `RPi.GPIO` are Linux-only (`sys_platform == 'linux'` in `pyproject.toml`). Client tests run on any platform.
- **Atomic file writes**: `cache.py` uses temp file + `os.replace` for persistence. Do not simplify to direct writes.
- **UnknownTagInbox**: In-memory only, max 20 entries, FIFO eviction. Data loss on restart is acceptable by design.
- **Docker networking**: Server uses `network_mode: host` for SSDP multicast (Sonos speaker discovery). This is required.
