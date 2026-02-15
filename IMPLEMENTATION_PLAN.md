# tontraeger: Implementation Plan

High-level plan for migrating from the current single-Pi monolith to the client-server
architecture described in ARCHITECTURE.md.

## Guiding Principles

- **Each step produces a working system.** No big-bang migration. At every checkpoint, the
  existing single-Pi setup continues to work, or the new split setup works end-to-end.
- **Server first, client second.** The server is the simpler component (no hardware deps)
  and can be developed and tested on any machine. The client adaption depends on the server
  API existing.
- **Move files, then adapt.** Restructure the monorepo first with minimal code changes, then
  layer on new functionality.

## Phase 1: Monorepo Restructure

**Goal:** Split the single `tontraeger/` package into `server/` and `client/` directories with
separate `pyproject.toml` files, while keeping the current single-Pi behavior working.

### Step 1.1: Create directory structure

Create the monorepo layout:

```
tontraeger/
├── server/
│   ├── pyproject.toml
│   └── tontraeger_server/
│       └── __init__.py
├── client/
│   ├── pyproject.toml
│   └── tontraeger_client/
│       └── __init__.py
└── Makefile
```

### Step 1.2: Move server files

Copy files to their new homes:

- `tontraeger/tag_mapper.py` → `server/tontraeger_server/tag_mapper.py`
- `tontraeger/web.py` → `server/tontraeger_server/web.py`
- `tontraeger/sonos_api.py` → `server/tontraeger_server/sonos_api.py` (for Now Playing)
- `tontraeger/config.py` → `server/tontraeger_server/config.py`

Fix internal imports (`from tontraeger.X` → `from tontraeger_server.X`).

Create `server/pyproject.toml` with dependencies: `flask`, `soco`, `python-dotenv`.

### Step 1.3: Move client files

Copy files to their new homes:

- `tontraeger/rfid_reader.py` → `client/tontraeger_client/rfid_reader.py`
- `tontraeger/sonos_api.py` → `client/tontraeger_client/sonos_api.py`
- `tontraeger/control.py` → `client/tontraeger_client/control.py`
- `tontraeger/config.py` → `client/tontraeger_client/config.py`

Fix internal imports (`from tontraeger.X` → `from tontraeger_client.X`).

Create `client/pyproject.toml` with dependencies: `soco`, `requests`, `python-dotenv`,
`mfrc522` (linux), `RPi.GPIO` (linux).

### Step 1.4: Move and adapt tests

- `tests/test_tag_mapper.py` → `server/tests/test_tag_mapper.py`
- `tests/test_web.py` → `server/tests/test_web.py`
- `tests/test_sonos_api.py` → `server/tests/test_sonos_api.py` (keep for Now Playing)
  and `client/tests/test_sonos_api.py` (keep for playback)
- `tests/test_control.py` → `client/tests/test_control.py`

Fix imports. Verify all tests pass.

### Step 1.5: Update top-level Makefile

Add targets:

- `make test-server` — run server tests
- `make test-client` — run client tests
- `make test` — run all tests
- `make lint`, `make format`, `make typecheck` — adapted for both packages

**Checkpoint:** All existing tests pass in their new locations. No functional changes yet.

---

## Phase 2: Server JSON API

**Goal:** Add the three JSON API endpoints to the Flask app. This is the only new server-side
code. Everything else is file moves and import fixes.

### Step 2.1: Add `content_hash()` to TagMapper

Add a method to `tag_mapper.py` that returns a SHA-256 hash of all mappings, sorted and
serialized. This serves as the ETag for conditional polling.

```python
def content_hash(self) -> str:
    """SHA-256 of all mappings, for use as ETag."""
    ...
```

Write tests.

### Step 2.2: Add `GET /api/mappings`

Add a Flask route that returns all mappings as JSON with an ETag header. Support
`If-None-Match` for conditional responses (return 304 if ETag matches).

Write tests: verify JSON shape, verify ETag header present, verify 304 on matching ETag,
verify 200 with new data after a mapping change.

### Step 2.3: Add unknown tag inbox and endpoints

Implement the in-memory unknown tag store (dict, max 20, FIFO):

- `POST /api/unknown-tags` — accepts `{"tag_uid": "..."}`, stores in inbox with timestamp
  and scan count. Deduplicates (same UID increments count and updates `last_seen`).
- `GET /api/unknown-tags` — returns all entries as JSON.

Write tests.

### Step 2.4: Adapt "Now Playing" with speaker picker

Change `GET /now-playing` to accept an optional `?speaker=X` query parameter. If provided,
discover speakers and query the named one. If not provided, fall back to the configured
default.

Update the web UI template: replace the single "Now Playing" button with a speaker picker
dropdown that's populated by a new `GET /api/speakers` endpoint (returns discovered speaker
names). On selection, fetch the track from that speaker.

Write tests.

### Step 2.5: Update web UI to show unknown tags

Add a section to the HTML template (below the "New Mapping" form or integrated into it)
that shows recently scanned unknown tags. Each entry shows the tag UID with a button to
pre-fill the "Tag UID" field in the mapping form.

Fetch unknown tags via JavaScript (`GET /api/unknown-tags`), either on page load or
periodically.

**Checkpoint:** Server runs standalone with all new API endpoints working. Testable with
`curl`. Web UI shows unknown tags and has speaker picker for Now Playing.

---

## Phase 3: Client Cache and Sync

**Goal:** Build the client's mapping cache (in-memory dict + JSON file) and HTTP sync module.
These are the two new client-side files.

### Step 3.1: Implement `cache.py`

The mapping cache module:

- `MappingCache` class with:
  - `__init__(cache_path: str)` — loads from JSON file if it exists
  - `get_uri(tag_uid: str) -> Optional[str]` — O(1) dict lookup
  - `update(mappings: list[dict]) -> None` — replaces in-memory dict, writes JSON to disk
    (atomic: write to temp file, then rename)
  - `all_mappings() -> dict[str, tuple[str, str]]` — for debugging/logging

Write tests: empty cache, load from file, update and persist, get_uri hit/miss, atomic
write doesn't corrupt on crash (write to temp, rename), file not found on first boot.

### Step 3.2: Implement `sync.py`

The HTTP sync module:

- `MappingSync` class with:
  - `__init__(server_url: str, cache: MappingCache)` — stores server URL and cache reference
  - `poll() -> bool` — single poll cycle: `GET /api/mappings` with `If-None-Match`.
    Returns True if cache was updated. Handles connection errors gracefully (log and return
    False).
  - `report_unknown_tag(tag_uid: str) -> None` — `POST /api/unknown-tags`. Fire-and-forget
    (log errors, don't crash).
  - `run(interval: float = 10.0) -> None` — async loop: call `poll()` every `interval`
    seconds. Runs forever.

Write tests with mocked HTTP: test 200 updates cache, test 304 skips update, test
connection error doesn't crash, test ETag sent on subsequent polls, test unknown tag POST.

### Step 3.3: Adapt `control.py` to use cache

Change `PlaybackController` to take a `MappingCache` instead of a `TagMapper`:

- `handle_tag()` calls `cache.get_uri()` instead of `mapper.get_uri()`
- On unknown tag: call `sync.report_unknown_tag()` instead of raising an exception

Update the `TagReader` protocol — unchanged.

Adapt existing tests.

**Checkpoint:** Client cache and sync modules work in isolation with mocked HTTP. Control
loop works with a cache.

---

## Phase 4: Client Entrypoint

**Goal:** Wire everything together in the client's `main.py` so the client runs as a single
process with concurrent RFID reading and HTTP sync.

### Step 4.1: Implement `client/tontraeger_client/main.py`

The entrypoint:

1. Load config from `.env` (speaker name, server address)
2. Create `MappingCache` (loads from disk)
3. Create `SonosAPI` (discovers speaker)
4. Create `MappingSync` (server URL, cache reference)
5. Create `PlaybackController` (sonos_api, cache)
6. Create `RFIDReader`
7. Run concurrently:
   - `sync.run()` — polling loop (every 10s)
   - `main_loop(reader, controller)` — RFID reading loop
8. Graceful shutdown on SIGINT/SIGTERM

Use `asyncio` to run both loops concurrently. The sync poll can run in an executor thread
(since `requests` is blocking) or use `aiohttp` — prefer the simpler option.

### Step 4.2: Implement `server/tontraeger_server/main.py`

Simple entrypoint that starts Flask:

```python
from tontraeger_server.web import app

def main():
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    main()
```

**Checkpoint:** Client and server can both start independently. Client polls server, receives
mappings, caches them, reads tags, plays music. Full end-to-end flow works.

---

## Phase 5: Deployment

**Goal:** Containerize the server. Set up systemd for the client. Adapt deployment scripts.

### Step 5.1: Server Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY server/ .
RUN pip install .
EXPOSE 5000
VOLUME /app/data
CMD ["python", "-m", "tontraeger_server.main"]
```

SQLite database (`tags.db`) lives on a mounted volume so it survives container recreation.

Test: `docker build`, `docker run`, `curl` the API.

### Step 5.2: Client systemd unit

Create a systemd service file for the client:

```ini
[Unit]
Description=tontraeger Client
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 -m tontraeger_client.main
WorkingDirectory=/home/pi/tontraeger
Restart=always
RestartSec=5
Environment=SONOS_SPEAKER_NAME=Wohnzimmer
Environment=tontraeger_SERVER=http://tontraeger.local:5000

[Install]
WantedBy=multi-user.target
```

### Step 5.3: Adapt deployment script

Update `sync_to_pi.sh` (or replace with Makefile targets):

- `make deploy-client` — rsync client package to Pi, restart systemd unit
- `make deploy-server` — build and push Docker image (or `docker compose up -d`)

### Step 5.4: Migrate existing data

The existing `tags.db` from the Pi is the SQLite database. Copy it to the server's volume
mount. No schema changes needed — `tag_mapper.py` is unchanged except for the new
`content_hash()` method.

**Checkpoint:** Server runs in a container. Client runs on Pi via systemd. End-to-end
workflow works: manage mappings in web UI, tap cards on Pi, music plays.

---

## Phase 6: Cleanup

**Goal:** Remove the old single-Pi code and finalize the migration.

### Step 6.1: Remove old `tontraeger/` package

Once the server and client are running independently, remove the original `tontraeger/`
directory and its `tests/` directory. Remove the old top-level `pyproject.toml`.

### Step 6.2: Update documentation

Update `README.md`:
- New architecture overview
- Server setup (container)
- Client setup (Pi)
- Configuration reference (`.env` on Pi, environment variables on server)
- Troubleshooting / runbooks

Update `INSTALL.md` for the new split setup.

### Step 6.3: Update Makefile

Final top-level Makefile targets:

- `make test` — run all tests (server + client)
- `make test-server` / `make test-client`
- `make lint` / `make format` / `make typecheck`
- `make deploy-server` / `make deploy-client`
- `make docker-build` — build server container

**Checkpoint:** Clean repository. Old code removed. Documentation current. All tests pass.

---

## Summary

| Phase | What                       | New files              | Changed files                     |
|-------|----------------------------|------------------------|-----------------------------------|
| 1     | Monorepo restructure       | directory layout       | imports in all moved files        |
| 2     | Server JSON API            | —                      | `tag_mapper.py`, `web.py`         |
| 3     | Client cache and sync      | `cache.py`, `sync.py`  | `control.py`                      |
| 4     | Client entrypoint          | two `main.py` files    | —                                 |
| 5     | Deployment                 | Dockerfile, systemd    | `sync_to_pi.sh` / Makefile        |
| 6     | Cleanup                    | —                      | README, INSTALL, Makefile         |

Each phase is independently committable and testable. Phases 2 and 3 are the core
functional work; the rest is restructuring and packaging.
