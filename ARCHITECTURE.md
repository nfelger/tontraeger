# tontraeger: Architecture

## Design Principle

The critical path — place card, play music — must work without any network dependency beyond
the Sonos speaker itself. The server is a convenience for managing mappings, not a runtime
requirement for playback.

## Server (runs as a container, single Flask process, port 3000)

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

## Client (Raspberry Pi with PN532 NFC reader)

Tag presence detection, local lookup, and direct Sonos control:

- **NFC Daemon** (C, libnfc) — detects PN532 tag presence via I2C, emits `PRESENT`/`REMOVED`
  events on stdout. Spawned by Python as a child process.
- **PlaybackController** — reacts to presence events: place = play, remove = pause
- **Local Mapping Cache** — in-memory dict for O(1) lookup, backed by a JSON file on disk
  for persistence across reboots
- **Sonos API** (SoCo, async) — lazy discovery with auto-rediscovery on error
- **HTTP Sync** — polls `GET /api/mappings` every 10 seconds with `If-None-Match` (ETag).
  Reports unknown tags via `POST /api/unknown-tags`.

## Data Flow

```
                        ┌──────────────────────────────────┐
                        │        SERVER (Flask :3000)       │
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
                        │  NFC Daemon ──► PlaybackController │
                        │  (C, PN532)          │            │
                        │                      ▼            │
                        │                  SonosAPI ──► 🔊  │
                        │                  (SoCo, async)    │
                        └───────────────────────────────────┘
```

## Playback Path (no server dependency)

1. User places NFC tag on reader
2. C daemon detects tag, emits `PRESENT <uid>` on stdout
3. Python reads the event, looks up UID in local cache
4. If found: `await SonosAPI.play_uri(uri)`
5. If not found: log locally, fire-and-forget report to server via `POST /api/unknown-tags`
6. User removes tag from reader
7. C daemon detects removal (3 consecutive poll misses), emits `REMOVED <uid>`
8. Python reads the event: `await SonosAPI.stop_playback()`

## Mapping Sync Path

1. Client polls `GET /api/mappings` every 10 seconds
2. Request includes `If-None-Match` header with the ETag from the last response
3. If mappings haven't changed: server returns `304 Not Modified` (~100 bytes)
4. If mappings changed: server returns full JSON payload + new ETag
5. Client replaces in-memory dict and writes `mappings.json` to disk
6. If server unreachable: client continues with cached mappings, retries next interval

The ETag is a content hash (SHA-256 of the sorted, serialized mappings). It is stateless
and survives server restarts — no version counter needed.

## Client Boot Sequence

1. Load `mappings.json` from disk into in-memory dict (if file exists)
2. Best-effort initial sync (single poll, failure is non-fatal)
3. Start background tasks: `sync.run()` (polls every 10s), `sonos_api.discover()`
4. Start `nfc_reader` coroutine — spawns C daemon, processes events forever
5. If server unreachable: continue with cached mappings, keep polling

## New Mapping Workflow

1. User plays something on Sonos (via Spotify app, etc.)
2. User opens tontraeger web UI, clicks "Now Playing"
3. Web UI shows speaker picker (discovered via SoCo on server), fetches current track URI
4. User places new NFC tag on any client reader
5. Client reports unknown tag UID to server via `POST /api/unknown-tags`
6. Web UI shows the UID in "recently scanned unknown tags"
7. User creates mapping: tag UID + media URI + name
8. Server saves to SQLite (ETag changes)
9. Client picks up new mapping on next poll (within 10 seconds)
10. Card works on all clients

Note: If faster propagation is needed during the mapping workflow, the client can be
configured to poll immediately after reporting an unknown tag, since that's when a new
mapping is most likely being created.

## Design Decisions

| Decision                  | Choice                                                   |
|---------------------------|----------------------------------------------------------|
| Communication protocol    | HTTP/JSON (on existing Flask app, single port)           |
| Sync mechanism            | Client polls every 10s with ETag for conditional fetch   |
| Sync granularity          | Full snapshot (data is tiny, ~5KB)                       |
| Change detection          | Content hash as ETag (stateless, survives server restart) |
| Tag hardware              | PN532 via libnfc (I2C)                                   |
| NFC daemon                | C child process, PRESENT/REMOVED protocol on stdout      |
| Server discovery          | mDNS (`tontraeger.local`)                                  |
| Authentication            | None (trusted home network)                              |
| Tag mappings scope        | Global (shared across all clients)                       |
| "Now Playing"             | Server retains read-only SoCo, user picks speaker        |
| Unknown tag reporting     | Clients POST to server, shown in web UI                  |
| Unknown tag inbox         | In-memory, max 20 entries, FIFO eviction                 |
| Client cache              | In-memory dict + JSON file on disk                       |
| Client speaker config     | Local `.env` file on the Pi                              |
| Server process model      | Single Flask process, single port (3000)                 |
| Repository structure      | Monorepo                                                 |
| Server deployment         | Container                                                |

## JSON API

```
GET /api/mappings
  Response: 200 with JSON body + ETag header
  Response: 304 Not Modified (if If-None-Match matches current ETag)

  Body:
  {
    "mappings": [
      {"tag_uid": "04:ab:cd:12:34:56:78", "media_uri": "https://open.spotify.com/album/...", "name": "Kids Mix"}
    ]
  }

POST /api/unknown-tags
  Request body: {"tag_uid": "04:ab:cd:12:34:56:78"}
  Response: 200 OK

GET /api/unknown-tags
  Response: 200 with JSON body
  Body:
  {
    "tags": [
      {"tag_uid": "04:ab:cd:12:34:56:78", "first_seen": "2025-03-01T14:30:00Z", "last_seen": "2025-03-01T14:30:05Z", "scan_count": 3}
    ]
  }
```

HTML routes:

```
GET  /                          → HTML UI
POST /mappings                  → Create mapping (HTML form)
POST /mappings/<uid>/delete     → Delete mapping (HTML form)
GET  /now-playing?speaker=X     → JSON: current track URI
```
