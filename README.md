# tontraeger

A Raspberry Pi-based Sonos controller that uses RFID tags to trigger music playback. Tap a
card to play an album; tap a stop card to pause.

## Architecture

tontraeger has two components:

- **Server** (Docker container, any machine on your LAN): Flask web UI for managing
  tag-to-URI mappings, JSON API for clients, and read-only Sonos access for the "Now
  Playing" mapping workflow. SQLite is the source of truth for all mappings.
- **Client** (Raspberry Pi with RFID hardware): reads RFID tags, looks up the mapped URI
  in a local cache, and plays it directly on a Sonos speaker. Polls the server every 10
  seconds to pick up mapping changes.

The critical path — tap card, play music — has no dependency on the server. The local cache
persists across reboots and continues to work if the server is unreachable.

```
           SERVER (Flask :5000)                    CLIENT (Pi)
           │                                       │
      Web UI ◄────► TagMapper (SQLite)        HTTP Sync (polls every 10s)
           │               │                      │
         JSON API ──────── ETag              Mapping Cache ◄── mappings.json
                                                  │
                                             RFID Reader ──► Control Loop
                                                              │
                                                          SonosAPI ──► 🔊
```

## Setup

See [INSTALL.md](INSTALL.md) for full instructions. The short version:

```bash
cp .env.sample .env       # fill in your values
make run-server           # start the server container
make sync-client          # deploy client code to the Pi
make install-client-service  # install + enable systemd unit on the Pi
```

## Adding a New Mapping

1. Play something on Sonos (via the Spotify app, etc.)
2. Open the web UI at `http://tontraeger.local:5000`
3. Click **Now Playing** and pick your speaker — the URI is pre-filled
4. Tap the RFID card you want to assign — the client reports the unknown tag to the server
   and it appears in the **Recently Scanned** list
5. Click the tag UID to pre-fill it, enter a name, click **Add Mapping**
6. The card works within 10 seconds (next sync cycle)

## Configuration

All configuration lives in `.env` (copy from `.env.sample`):

| Variable | Used by | Default | Description |
|---|---|---|---|
| `SONOS_SPEAKER_NAME` | server + client | `Wohnzimmer` | Default Sonos speaker name |
| `PI_HOST` | deploy targets | `pi@tontraeger.local` | SSH target for the Pi |
| `PI_DIR` | deploy targets | `/home/pi/tontraeger` | Deployment directory on the Pi |
| `TONTRAEGER_SERVER` | client | `http://tontraeger.local:5000` | Server URL |
| `TONTRAEGER_CACHE_PATH` | client | `/home/pi/tontraeger/client/mappings.json` | Local mapping cache path on Pi |

## Development

```bash
make test          # run all tests (server + client)
make test-server   # server tests only
make test-client   # client tests only
make check         # lint + typecheck + test
make web           # start Flask server locally (without Docker)
```
