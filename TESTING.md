# Manual Testing Plan: Post-Rearchitecture Verification

The rearchitecture replaced direct SQLite access in the client with an HTTP sync
layer (MappingSync + MappingCache). These are the scenarios that matter but automated
tests can't cover: real hardware, actual network conditions, deployment, and the
integrated end-to-end workflows.

Run `make check` first. All 86 automated tests must pass before starting.

---

## Prerequisites

- Raspberry Pi with MFRC522 reader connected via SPI
- At least two RFID tags
- Sonos speaker reachable on the local network
- Server `.env` with `SONOS_SPEAKER_NAME`, `TONTRAEGER_DB_PATH`
- Client `.env` with `SONOS_SPEAKER_NAME`, `TONTRAEGER_SERVER`, `TONTRAEGER_CACHE_PATH`

---

## A. Server Smoke Tests (no Pi required)

Start the server locally: `make web` (or `make run-server` for Docker).

### A1. Web UI baseline

1. Open `http://localhost:5000` in a browser.
2. Confirm the page loads — header, "New Mapping" form, empty mappings list.
3. Add a mapping: any tag UID, any URI (e.g. `STOP`), a name. Submit.
4. Confirm a flash message appears and the mapping shows in the list.
5. Delete the mapping. Confirm the list is empty again.

### A2. ETag conditional GET

```bash
# First request — expect 200 with ETag header
curl -i http://localhost:5000/api/mappings

# Copy the ETag value from above, then:
curl -i -H 'If-None-Match: <etag>' http://localhost:5000/api/mappings
# Expect: HTTP 304, no body
```

Add a mapping via the web UI, then repeat the second curl with the old ETag.
Expect: HTTP 200 with the new mapping in the body and a different ETag.

### A3. Unknown tag API

```bash
# Report an unknown tag
curl -X POST http://localhost:5000/api/unknown-tags \
  -H 'Content-Type: application/json' \
  -d '{"tag_uid": "TEST123"}'
# Expect: {"ok": true}

# Fetch unknown tags
curl http://localhost:5000/api/unknown-tags
# Expect: {"tags": [{"tag_uid": "TEST123", "scan_count": 1, ...}]}

# Report the same tag again
curl -X POST http://localhost:5000/api/unknown-tags \
  -H 'Content-Type: application/json' \
  -d '{"tag_uid": "TEST123"}'
curl http://localhost:5000/api/unknown-tags
# Expect: scan_count == 2, last_seen updated, still only one entry
```

### A4. Unknown tag FIFO eviction

Post 21 distinct tag UIDs (e.g. `TAG_01` through `TAG_21`).
Fetch `/api/unknown-tags`. Expect exactly 20 entries — `TAG_01` is gone, `TAG_02`
through `TAG_21` remain.

### A5. Speaker discovery (optional — requires Sonos on LAN)

```bash
curl http://localhost:5000/api/speakers
# Expect: {"speakers": ["<speaker name>", ...]}
```

In the browser, confirm the speaker dropdown in "New Mapping" populates
automatically and the "Now Playing" button becomes active after selecting a speaker.

---

## B. Client — Offline Playback (server not running)

These tests verify the critical path works without any server dependency.

### B1. Boot from cold cache

1. Delete `mappings.json` (the `TONTRAEGER_CACHE_PATH`).
2. Ensure the server is stopped.
3. Start the client: `make control`.
4. Confirm startup logs show "Performing initial sync..." followed by a graceful
   failure (e.g. "Failed to poll server: ...").
5. Tap a card. Confirm in logs: "Unknown tag: ..." (not a crash). No playback.

**Why this matters:** The old client would crash attempting SQLite access. The new
client must degrade gracefully.

### B2. Boot from warm cache

1. With the server running, start the client and let it sync at least once.
   Verify `mappings.json` exists on disk.
2. Stop the server.
3. Stop and restart the client.
4. Confirm in logs: cache loaded from disk, initial poll failed gracefully.
5. Tap the card mapped in step 1. Confirm Sonos plays the correct track.
6. Tap it again within 5 seconds. Confirm no second play (debounce active in logs).
7. Wait 6 seconds, tap again. Confirm Sonos plays again.

**Why this matters:** Survives Pi reboot with server unavailable — the core
reliability guarantee of the architecture.

### B3. STOP command (offline)

1. With the server up, add a mapping: any tag UID, `STOP` as media URI.
2. Let the client sync the mapping.
3. Stop the server.
4. Start music on Sonos (any method).
5. Tap the STOP card. Confirm Sonos pauses.

---

## C. Full Integration (server + client running)

### C1. New mapping propagates within 10 seconds

1. Start client and server.
2. Tap a card that has no mapping. Confirm log: "Unknown tag: ..." and the
   unknown tag appears in the web UI within a few seconds.
3. In the web UI, click "Use" next to the tag UID — it should fill the Tag UID field.
4. Add a Spotify share link or Sonos URI in the Media URI field. Submit.
5. Without restarting the client, wait up to 10 seconds.
6. Tap the same card. Confirm Sonos plays the track.

**Critical check:** The client must not require a restart to pick up the new mapping.

### C2. ETag efficiency — verify 304s in production

Add server-side logging or inspect client logs. After an initial successful sync:

1. Wait 10 seconds (one poll cycle).
2. Confirm logs show no cache update (poll returned 304, cache unchanged).
3. Add a mapping on the server.
4. Wait up to 10 seconds.
5. Confirm logs show a cache update (poll returned 200).

### C3. Unknown tag round-trip and "Use" button

1. Tap an unmapped card.
2. Open the web UI. Confirm the tag appears in "Recently Scanned" within 5 seconds
   (the UI polls `/api/unknown-tags` every 5 seconds).
3. Click "Use" — confirm the Tag UID field is populated.
4. Complete the mapping form with a name and URI.
5. Wait for client sync. Tap the card. Confirm playback.

### C4. Spotify share link playback

1. Copy a Spotify album or playlist share link
   (format: `https://open.spotify.com/...`).
2. Create a mapping with this URI.
3. Let the client sync.
4. Tap the card. Confirm Sonos plays from Spotify (not an error about URI format).

**Why this matters:** Spotify links use `ShareLinkPlugin` instead of
`add_uri_to_queue` — this branch is distinct from regular URIs.

---

## D. Failure Scenarios

### D1. Server goes down mid-session

1. Client and server running, client has synced mappings.
2. Stop the server.
3. Wait 10+ seconds (one or more poll cycles).
4. Confirm client logs show graceful poll failures (warnings, not crashes).
5. Tap a mapped card. Confirm Sonos still plays.
6. Restart the server.
7. Wait for the next poll cycle. Confirm the client syncs successfully.

### D2. Server unreachable at boot, then comes back

1. Stop the server.
2. Start the client (with `mappings.json` from a previous session).
3. Tap a card. Confirm cached playback works.
4. Start the server.
5. Without restarting the client, wait 10 seconds.
6. Add a new mapping on the server.
7. Wait 10 more seconds. Tap the new card. Confirm playback.

### D3. Malformed server response

```bash
# Replace server with a mock that returns garbage
python3 -c "
from http.server import HTTPServer, BaseHTTPRequestHandler
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'not json')
    def log_message(self, *a): pass
HTTPServer(('', 5000), H).serve_forever()
"
```

Start the client against this mock. Confirm it logs a warning and does not crash.
Kill the mock and start the real server. Confirm the client recovers on the next poll.

---

## E. Deployment

### E1. Docker server

```bash
cp .env.sample .env  # edit SONOS_SPEAKER_NAME, TONTRAEGER_DB_PATH
make run-server
```

1. Confirm `docker compose up` completes without error.
2. Confirm `http://localhost:5000` responds with the web UI.
3. Confirm `GET /api/mappings` returns `{"mappings": []}` initially.
4. Restart the container (`docker compose restart`). Add a mapping before restart,
   confirm it persists after — the SQLite file is on a Docker volume.

### E2. systemd client service on Pi

```bash
make install-client-service
make sync-client
sudo systemctl start tontraeger-client
```

1. Check `sudo systemctl status tontraeger-client` — confirm active (running).
2. Check `journalctl -u tontraeger-client -n 50` — confirm clean startup log.
3. Kill the service: `sudo systemctl stop tontraeger-client`.
4. Confirm `systemctl status` shows stopped (not failed).
5. Simulate a crash: find the PID, `kill -9 <pid>`. Confirm systemd restarts it
   (the unit file should have `Restart=on-failure`).

---

## F. Edge Cases

### F1. Cache file is corrupted

1. Write garbage to `mappings.json`.
2. Start the client. Confirm it logs a warning and starts with an empty cache
   (not a crash).

*(The current code raises JSONDecodeError on corrupted cache — confirm the
behavior is at least a logged error rather than a silent hang.)*

### F2. Duplicate tag UIDs in mappings

Add the same tag UID twice via the API (e.g. `curl -X POST /mappings` twice with
the same `tag_uid`). Confirm the second insert updates the URI (upsert semantics)
and `GET /api/mappings` returns exactly one entry for that UID.

### F3. Unknown tag not reported when server is down

1. Server stopped.
2. Tap an unmapped card.
3. Confirm client logs show "Unknown tag: ..." and "Failed to report unknown tag..."
   — no crash, no hang.

### F4. Multiple clients (if applicable)

If two Pi units are available, both running the client against the same server:

1. Add a mapping on the server.
2. Confirm both clients pick it up within 10 seconds independently.
3. Tap the card on one Pi. Confirm only that Pi's Sonos plays.

---

## Test Result Log

| Test | Pass / Fail / Skip | Notes |
|------|-------------------|-------|
| A1 Web UI baseline | | |
| A2 ETag conditional GET | | |
| A3 Unknown tag API | | |
| A4 Unknown tag eviction | | |
| A5 Speaker discovery | | |
| B1 Cold cache boot | | |
| B2 Warm cache boot | | |
| B3 STOP offline | | |
| C1 Mapping propagates <10s | | |
| C2 ETag 304 efficiency | | |
| C3 Unknown tag round-trip | | |
| C4 Spotify share link | | |
| D1 Server down mid-session | | |
| D2 Server unreachable at boot | | |
| D3 Malformed server response | | |
| E1 Docker server | | |
| E2 systemd service | | |
| F1 Corrupted cache file | | |
| F2 Duplicate tag UID | | |
| F3 Unknown tag, server down | | |
| F4 Multiple clients | | |
