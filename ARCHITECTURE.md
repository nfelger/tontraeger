# SpotiBox: Client-Server Architecture Planning

## Current Architecture

Everything runs on a single Raspberry Pi:

- **RFID Reader** (`rfid_reader.py`) — reads tags via SPI/GPIO
- **Playback Controller** (`control.py`) — async event loop, debouncing, orchestration
- **Tag Mapper** (`tag_mapper.py`) — SQLite database mapping tag UIDs to media URIs
- **Sonos API** (`sonos_api.py`) — speaker discovery and playback control via SoCo
- **Web UI** (`web.py`) — Flask app for managing mappings

## Proposed Architecture

Split into two components:

- **Server** (any machine on the network): Web UI + Sonos control + tag mapping DB + tag submission API
- **Client** (Raspberry Pi with RFID hardware): Tag reading + forwarding tag UIDs to server

## Key Questions

### 1. Communication Protocol

How does the client send tag UIDs to the server?

- **HTTP/REST** — Simplest. Client POSTs `{tag_uid: "..."}` to a server endpoint. Easy to
  debug, works with existing Flask app. Request-response only, so the server can't push
  status back without polling.
- **WebSocket** — Bidirectional. Server can push acknowledgments or "now playing" info back
  to the client. Useful if the client has an LED or display. More complex.
- **MQTT** — Pub/sub, common in IoT. Good for multiple clients and loose coupling. Requires
  a broker (e.g., Mosquitto) as an additional service.

**Core question:** Does the client need to receive anything back from the server, or is it
purely fire-and-forget?

### 2. Debouncing Location

Currently the playback controller debounces duplicate tags (5-second window). Where should
this live?

- **Client-side** — reduces network traffic, but each client debounces independently.
- **Server-side** — centralized, single source of truth, but every duplicate generates a
  network request.
- **Both** — client does coarse filtering, server enforces correctness.

**Core question:** Is the traffic volume low enough that server-side-only debouncing is fine?

### 3. Network Reliability and Failure Modes

A network boundary introduces new failure scenarios:

- What happens when the server is unreachable? Queue and retry, or drop?
- Should the client provide local feedback (LED, buzzer) for server acknowledgment?
- What's the timeout for tag submission requests?
- Should the server expose a health check endpoint?

**Core question:** How does the user know their tap "worked" when there's a network hop
involved? This matters especially if children are the primary users.

### 4. Client Discovery of the Server

How does the client find the server?

- **Static configuration** — hardcoded IP/hostname. Simple but fragile.
- **mDNS/Avahi** — server advertises as `spotibox.local`. Zero-config, common on home
  networks.
- **Broadcast discovery** — client sends discovery packet. Fully automatic but more complex.

**Core question:** Is mDNS reliable enough on the home network?

### 5. Multiple Clients

Client-server naturally enables multiple readers. Even if there's only one now, the
architecture should make a conscious choice:

- Can different readers control different Sonos speakers?
- Does the client identify itself so the server routes to the right speaker?
- Are tag-to-URI mappings global or per-reader?
- How does the web UI handle multiple readers?

### 6. Security and Authentication

- Should the server accept tag submissions from any device, or require an API key?
- The web UI has no authentication — does the network split change the threat model?
- Is "trusted home network" a sufficient security boundary?

### 7. Latency

Users expect near-instant playback after tapping a card. The network hop adds latency:

- Local network HTTP is typically 1-5ms (negligible).
- Sonos speaker discovery could add seconds if done per-request (currently done at startup).

**Core question:** Should the server maintain a persistent Sonos connection, or re-discover on
each request? (Current code discovers at startup, so keeping the server long-running solves
this.)

### 8. Packaging and Deployment

Currently one package deployed via rsync. The split creates two deployment targets:

- **Server**: Flask + SoCo + SQLite. No hardware deps. Can run on any machine or in Docker.
- **Client**: MFRC522 + RPi.GPIO + HTTP client. Minimal deps, Pi-only.

Questions:
- Monorepo (e.g., `spotibox-server/` + `spotibox-client/`) or separate repos?
- Does the server run in Docker?
- How to keep client and server API-compatible across versions?

### 9. API Contract

Two components communicating over a network need a defined contract:

- Request/response shape for tag submission.
- Should the server expose tag mapping CRUD as a REST API? (Currently only HTML endpoints.)
- If the web UI might become a separate SPA in the future, a proper REST API underneath
  would be needed anyway.

### 10. Testing

The current tests mock hardware at the Python level. The split changes testing:

- **Client tests**: mock the HTTP call, verify tag UIDs are sent correctly.
- **Server tests**: mock incoming requests, verify Sonos commands fire.
- **Integration tests**: need both components (or a harness simulating the other side).
- Existing `PlaybackController` tests need reworking — the controller's input changes from
  local reader to HTTP request.

### 11. Process Management

Currently two processes on the Pi (`make control` + `make web`). In the new architecture:

- **Server**: single process handling tag submission API + web UI.
- **Client**: single process reading tags and sending HTTP requests.
- What supervises these? Systemd? Docker? Both?
- Does the client need a watchdog for automatic restart?
