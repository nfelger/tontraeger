# SpotiBox: Client-Server Architecture

## Current Architecture

Everything runs on a single Raspberry Pi:

- **RFID Reader** (`rfid_reader.py`) — reads tags via SPI/GPIO
- **Playback Controller** (`control.py`) — async event loop, debouncing, orchestration
- **Tag Mapper** (`tag_mapper.py`) — SQLite database mapping tag UIDs to media URIs
- **Sonos API** (`sonos_api.py`) — speaker discovery and playback control via SoCo
- **Web UI** (`web.py`) — Flask app for managing mappings

## Target Architecture

### Design Principle

The critical path — tap card, play music — must work without any network dependency beyond
the Sonos speaker itself. The server is a convenience for managing mappings, not a runtime
requirement for playback.

### Server (runs as a container, single Flask process, port 5000)

Tag mapping management, distribution, and mapping workflow support:

- **Web UI** (Flask) — CRUD for tag-to-URI mappings, unchanged look and feel
- **JSON API** (Flask, same process and port) — `GET /api/mappings`,
  `POST /api/unknown-tags`, `GET /api/unknown-tags`
- **Tag Mapper** (SQLite) — source of truth for all mappings
- **Read-only Sonos access** (SoCo) — "Now Playing" feature for the web UI, where the user
  picks from discovered speakers. Independent of clients.
- **Unknown tag inbox** — in-memory dict (max 20 entries, FIFO eviction), receives reports
  of unrecognized tag scans from clients, displayed in the web UI to simplify creating new
  mappings. Lost on server restart (acceptable — tags can be re-scanned).

### Client (Raspberry Pi with RFID hardware)

Tag reading, local lookup, and direct Sonos control:

- **RFID Reader** (MFRC522) — reads tags, unchanged
- **Local Mapping Cache** — in-memory dict for O(1) lookup, backed by a JSON file on disk
  for persistence across reboots
- **Sonos API** (SoCo) — discovers and controls its speaker directly
- **HTTP Sync** — polls `GET /api/mappings` every 10 seconds with `If-None-Match` (ETag).
  Reports unknown tags via `POST /api/unknown-tags`. Uses standard HTTP — no new
  dependencies beyond `requests` (or stdlib `urllib`).
- **Debouncing** — 5-second duplicate suppression, client-side

### Data Flow

```
                        ┌──────────────────────────────────┐
                        │        SERVER (Flask :5000)       │
                        │                                   │
                        │  Web UI ◄────► TagMapper (SQLite) │
                        │    │               │              │
                        │    │          content hash        │
                        │    │               │              │
  ┌──────────┐         │  JSON API ◄────────┘              │
  │  Browser  │◄──HTTP──│    │                              │
  └──────────┘         │    │  SoCo (read-only,            │
                        │    │   "Now Playing")             │
                        │    │                              │
                        │  Unknown Tag Inbox (in-memory)    │
                        └────┼──────────────────────────────┘
                        HTTP │  GET /api/mappings (poll)
                             │  POST /api/unknown-tags
                             │
                        ┌────┼──────────────────────────────┐
                        │    ▼           CLIENT (Pi)        │
                        │                                   │
                        │  HTTP Sync (polls every 10s)      │
                        │    │                              │
                        │    ▼                              │
                        │  Mapping Cache ◄── mappings.json  │
                        │  (in-memory dict)    (on disk)    │
                        │    ▲                              │
                        │    │ lookup                       │
                        │    │                              │
                        │  RFID Reader ──► Control Loop     │
                        │                      │            │
                        │                      ▼            │
                        │                  SonosAPI ──► 🔊  │
                        │                  (SoCo)           │
                        └───────────────────────────────────┘
```

### Playback Path (no server dependency)

1. User taps RFID card on reader
2. `RFIDReader.read_tag()` returns tag UID
3. Debounce check (5-second window, client-side)
4. Lookup in local in-memory dict
5. If found and URI is "STOP": `SonosAPI.stop_playback()`
6. If found: `SonosAPI.play_uri(uri)`
7. If not found: log locally, report to server via `POST /api/unknown-tags`

### Mapping Sync Path

1. Client polls `GET /api/mappings` every 10 seconds
2. Request includes `If-None-Match` header with the ETag from the last response
3. If mappings haven't changed: server returns `304 Not Modified` (~100 bytes)
4. If mappings changed: server returns full JSON payload + new ETag
5. Client replaces in-memory dict and writes `mappings.json` to disk
6. If server unreachable: client continues with cached mappings, retries next interval

The ETag is a content hash (SHA-256 of the sorted, serialized mappings). It is stateless
and survives server restarts — no version counter needed.

### Client Boot Sequence

1. Load `mappings.json` from disk into in-memory dict (if file exists)
2. Start RFID reading loop immediately (works from cached mappings)
3. Concurrently, start polling `http://spotibox.local:5000/api/mappings`
4. On first successful poll: update dict and disk cache
5. If server unreachable: continue with cached mappings, keep polling

### New Mapping Workflow

1. User plays something on Sonos (via Spotify app, etc.)
2. User opens SpotiBox web UI, clicks "Now Playing"
3. Web UI shows speaker picker (discovered via SoCo on server), fetches current track URI
4. User taps new RFID card on any client reader
5. Client reports unknown tag UID to server via `POST /api/unknown-tags`
6. Web UI shows the UID in "recently scanned unknown tags"
7. User creates mapping: tag UID + media URI + name
8. Server saves to SQLite (ETag changes)
9. Client picks up new mapping on next poll (within 10 seconds)
10. Card works on all clients

Note: If faster propagation is needed during the mapping workflow, the client can be
configured to poll immediately after reporting an unknown tag, since that's when a new
mapping is most likely being created.

## Settled Decisions

| Decision                  | Choice                                                   |
|---------------------------|----------------------------------------------------------|
| Communication protocol    | HTTP/JSON (on existing Flask app, single port)           |
| Sync mechanism            | Client polls every 10s with ETag for conditional fetch   |
| Sync granularity          | Full snapshot (data is tiny, ~5KB)                       |
| Change detection          | Content hash as ETag (stateless, survives server restart) |
| Debouncing                | Client-side, 5-second window                             |
| Server discovery          | mDNS (`spotibox.local`)                                  |
| Authentication            | None (trusted home network)                              |
| Tag mappings scope        | Global (shared across all clients)                       |
| "Now Playing"             | Server retains read-only SoCo, user picks speaker        |
| Unknown tag reporting     | Clients POST to server, shown in web UI                  |
| Unknown tag inbox         | In-memory, max 20 entries, FIFO eviction                 |
| Client cache              | In-memory dict + JSON file on disk                       |
| Client speaker config     | Local `.env` file on the Pi                              |
| Server process model      | Single Flask process, single port (5000)                 |
| Repository structure      | Monorepo                                                 |
| Server deployment         | Container                                                |

## JSON API

Three new endpoints added to the existing Flask app:

```
GET /api/mappings
  Response: 200 with JSON body + ETag header
  Response: 304 Not Modified (if If-None-Match matches current ETag)

  Body:
  {
    "mappings": [
      {"tag_uid": "123456789", "media_uri": "https://open.spotify.com/album/...", "name": "Kids Mix"},
      {"tag_uid": "987654321", "media_uri": "STOP", "name": "Stop Card"}
    ]
  }

POST /api/unknown-tags
  Request body: {"tag_uid": "555555555"}
  Response: 200 OK

GET /api/unknown-tags
  Response: 200 with JSON body
  Body:
  {
    "tags": [
      {"tag_uid": "555555555", "first_seen": "2025-03-01T14:30:00Z", "last_seen": "2025-03-01T14:30:05Z", "scan_count": 3}
    ]
  }
```

Existing HTML routes remain unchanged:

```
GET  /                          → HTML UI
POST /mappings                  → Create mapping (HTML form)
POST /mappings/<uid>/delete     → Delete mapping (HTML form)
GET  /now-playing?speaker=X     → JSON: current track URI (add speaker param)
```

## Monorepo Structure

```
spotibox/
├── server/
│   ├── pyproject.toml          # flask, soco, python-dotenv
│   ├── Dockerfile
│   ├── spotibox_server/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── tag_mapper.py       # SQLite, adds content_hash() method
│   │   ├── web.py              # Flask UI + JSON API, adapted "Now Playing"
│   │   └── main.py             # Entrypoint
│   └── tests/
├── client/
│   ├── pyproject.toml          # soco, requests, mfrc522, RPi.GPIO, python-dotenv
│   ├── spotibox_client/
│   │   ├── __init__.py
│   │   ├── config.py           # Reads local .env (speaker name, server addr)
│   │   ├── rfid_reader.py      # Unchanged
│   │   ├── sonos_api.py        # Unchanged
│   │   ├── control.py          # Adapted: uses in-memory cache, not TagMapper
│   │   ├── cache.py            # In-memory dict + JSON file persistence
│   │   ├── sync.py             # HTTP polling + unknown tag reporting
│   │   └── main.py             # Starts sync + control loop concurrently
│   └── tests/
└── Makefile                    # Top-level targets
```

## Testing Strategy

**Server tests:**
- `tag_mapper.py` — existing tests carry over, add test for `content_hash()`
- `web.py` — adapt existing Flask tests, add tests for JSON API endpoints
  (`/api/mappings` with ETag, `/api/unknown-tags`), add speaker picker for "Now Playing"

**Client tests:**
- `cache.py` — test dict operations, JSON persistence, load-on-boot, atomic write
- `sync.py` — mock HTTP responses (200 with data, 304 not modified, connection error),
  test cache update on new data, test ETag handling, test unknown tag reporting
- `control.py` — adapt existing tests: use in-memory cache instead of TagMapper mock
- `sonos_api.py` — existing tests carry over unchanged

**Integration tests:**
- Spin up Flask test server + client sync, verify end-to-end mapping propagation
- Verify unknown tag appears in `GET /api/unknown-tags` after client POST

## Migration Path

The existing codebase maps cleanly to the new structure:

| Current file          | Server                             | Client                       |
|-----------------------|------------------------------------|------------------------------|
| `tag_mapper.py`       | `tag_mapper.py` (add content hash) | —                            |
| `web.py`              | `web.py` (add JSON API endpoints)  | —                            |
| `sonos_api.py`        | read-only for Now Playing          | `sonos_api.py` (unchanged)   |
| `control.py`          | —                                  | `control.py` (use cache)     |
| `rfid_reader.py`      | —                                  | `rfid_reader.py` (unchanged) |
| `config.py`           | `config.py`                        | `config.py`                  |
| —                     | —                                  | `sync.py` (new)              |
| —                     | —                                  | `cache.py` (new)             |
| —                     | `main.py` (new)                    | `main.py` (new)              |
