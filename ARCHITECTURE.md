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

The critical path — tap card, play music — should work without any network dependency
beyond the Sonos speaker itself. The server is only needed for managing mappings and is
not in the playback path.

### Server (runs as a container on any machine)

Tag mapping management and distribution:

- **Web UI** (Flask on port 5000) — CRUD for tag-to-URI mappings, unchanged look and feel
- **Tag Mapper** (SQLite) — source of truth for all mappings
- **gRPC Sync Service** (port 50051) — streams mapping snapshots to connected clients
- **Read-only Sonos access** (SoCo) — "Now Playing" feature for the web UI, where the user
  picks from discovered speakers. No coupling to clients for this.
- **Unknown tag inbox** — receives reports of unrecognized tag scans from clients, displayed
  in the web UI to simplify creating new mappings

### Client (Raspberry Pi with RFID hardware)

Tag reading, local lookup, and direct Sonos control:

- **RFID Reader** (MFRC522) — reads tags, unchanged
- **Local Mapping Cache** — in-memory dict for O(1) lookup, backed by a JSON file on disk
  for persistence across reboots
- **Sonos API** (SoCo) — discovers and controls its speaker directly
- **gRPC Sync Client** — maintains a streaming connection to the server, receives mapping
  snapshots, reports unknown tags
- **Debouncing** — 5-second duplicate suppression, client-side

### Data Flow

```
                        ┌──────────────────────────────────┐
                        │            SERVER                 │
                        │                                   │
                        │  Flask Web UI ◄──► TagMapper      │
                        │       │              (SQLite)     │
                        │       │                 │         │
                        │       │           ┌─────┘         │
                        │       ▼           ▼               │
  ┌──────────┐         │  gRPC Sync Service                │
  │  Browser  │◄──HTTP──│       │                           │
  └──────────┘         │       │  SoCo (read-only,         │
                        │       │   "Now Playing")          │
                        └───────┼───────────────────────────┘
                          gRPC  │  streaming snapshots
                          (TLS  │  + unknown tag reports
                        optional│
                        ┌───────┼───────────────────────────┐
                        │       ▼         CLIENT (Pi)       │
                        │                                   │
                        │  gRPC Sync Client                 │
                        │       │                           │
                        │       ▼                           │
                        │  Mapping Cache ◄── mappings.json  │
                        │  (in-memory dict)    (on disk)    │
                        │       ▲                           │
                        │       │ lookup                    │
                        │       │                           │
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
7. If not found: log locally, report to server as unknown tag

### Mapping Sync Path

1. Client opens `WatchMappings` gRPC server-side stream on startup
2. Server sends initial `MappingSnapshot` (full set of mappings + version number)
3. Client replaces in-memory dict and writes `mappings.json` to disk
4. On any mapping change via the web UI, server pushes a new full snapshot
5. Client updates dict and disk cache
6. If stream breaks: client retries with exponential backoff, operates from cache

### Client Boot Sequence

1. Load `mappings.json` from disk into in-memory dict (if file exists)
2. Start RFID reading loop immediately (works from cached mappings)
3. Concurrently, connect to server via mDNS (`spotibox.local:50051`)
4. On connect: receive fresh snapshot, update dict and disk cache
5. If server unreachable: continue with cached mappings, keep retrying

### New Mapping Workflow

1. User plays something on Sonos (via Spotify app, etc.)
2. User opens SpotiBox web UI, clicks "Now Playing"
3. Web UI shows speaker picker (discovered via SoCo on server), fetches current track URI
4. User taps new RFID card on any client reader
5. Client reports unknown tag UID to server
6. Web UI shows the UID in "recently scanned unknown tags"
7. User creates mapping: tag UID + media URI + name
8. Server saves to SQLite, pushes snapshot to all clients
9. Card works immediately on all clients

## Settled Decisions

| Decision                  | Choice                                         |
|---------------------------|-------------------------------------------------|
| Communication protocol    | gRPC                                            |
| Sync mechanism            | Server-side streaming, full snapshots per change |
| Sync granularity          | Full snapshot (data is tiny, ~5KB)               |
| Debouncing                | Client-side, 5-second window                    |
| Server discovery          | mDNS (`spotibox.local`)                         |
| Authentication            | None (trusted home network)                     |
| Tag mappings scope        | Global (shared across all clients)              |
| "Now Playing"             | Server retains read-only SoCo, user picks speaker |
| Unknown tag reporting     | Clients report to server, shown in web UI       |
| Client cache              | In-memory dict + JSON file on disk              |
| Client speaker config     | Local `.env` file on the Pi                     |
| Flask + gRPC coexistence  | Same process, separate ports (5000 + 50051)     |
| Repository structure      | Monorepo                                        |
| Server deployment         | Container                                       |

## gRPC Service Definition

```protobuf
syntax = "proto3";
package spotibox;

message TagMapping {
  string tag_uid = 1;
  string media_uri = 2;
  string name = 3;
}

message MappingSnapshot {
  uint64 version = 1;
  repeated TagMapping mappings = 2;
}

message GetMappingsRequest {
  uint64 last_known_version = 1;
}

message WatchMappingsRequest {
  uint64 last_known_version = 1;
}

message UnknownTagReport {
  string tag_uid = 1;
}

message UnknownTagAck {}

service SpotiBoxSync {
  // Get current full set of mappings (used on reconnect).
  rpc GetMappings(GetMappingsRequest) returns (MappingSnapshot);

  // Server-side stream: pushes a new MappingSnapshot on each change.
  rpc WatchMappings(WatchMappingsRequest) returns (stream MappingSnapshot);

  // Client reports an unrecognized tag scan.
  rpc ReportUnknownTag(UnknownTagReport) returns (UnknownTagAck);
}
```

## Monorepo Structure

```
spotibox/
├── proto/
│   └── spotibox.proto
├── server/
│   ├── pyproject.toml          # flask, soco, grpcio, protobuf
│   ├── Dockerfile
│   ├── spotibox_server/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── tag_mapper.py       # SQLite, adds observer/version hooks
│   │   ├── web.py              # Flask UI, adapted "Now Playing"
│   │   ├── grpc_server.py      # gRPC service implementation
│   │   └── main.py             # Starts Flask + gRPC in same process
│   └── tests/
├── client/
│   ├── pyproject.toml          # soco, grpcio, protobuf, mfrc522, RPi.GPIO
│   ├── spotibox_client/
│   │   ├── __init__.py
│   │   ├── config.py           # Reads local .env (speaker name, server addr)
│   │   ├── rfid_reader.py      # Unchanged
│   │   ├── sonos_api.py        # Unchanged
│   │   ├── control.py          # Adapted: uses in-memory cache, not TagMapper
│   │   ├── cache.py            # In-memory dict + JSON file persistence
│   │   ├── sync.py             # gRPC client: streaming + unknown tag reports
│   │   └── main.py             # Starts sync + control loop concurrently
│   └── tests/
└── Makefile                    # Proto generation, top-level targets
```

## Testing Strategy

**Server tests:**
- `tag_mapper.py` — unchanged, existing tests carry over
- `web.py` — adapt existing Flask tests, add speaker picker for "Now Playing"
- `grpc_server.py` — test snapshot generation, stream push on mutation, unknown tag storage

**Client tests:**
- `cache.py` — test dict operations, JSON persistence, load-on-boot
- `sync.py` — mock gRPC channel, test snapshot application, reconnect behavior
- `control.py` — adapt existing tests: use in-memory cache instead of TagMapper mock
- `sonos_api.py` — existing tests carry over unchanged

**Integration tests:**
- Spin up server + mock client, verify end-to-end sync
- Verify mapping change propagates through stream to client cache

## Migration Path

The existing codebase maps cleanly to the new structure:

| Current file          | Server                        | Client                       |
|-----------------------|-------------------------------|------------------------------|
| `tag_mapper.py`       | `tag_mapper.py` (add version) | —                            |
| `web.py`              | `web.py` (adapt Now Playing)  | —                            |
| `sonos_api.py`        | read-only for Now Playing     | `sonos_api.py` (unchanged)   |
| `control.py`          | —                             | `control.py` (use cache)     |
| `rfid_reader.py`      | —                             | `rfid_reader.py` (unchanged) |
| `config.py`           | `config.py`                   | `config.py`                  |
| —                     | `grpc_server.py` (new)        | `sync.py` (new)              |
| —                     | `main.py` (new)               | `cache.py` (new)             |
| —                     | —                             | `main.py` (new)              |
