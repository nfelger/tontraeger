# tontraeger

A Raspberry Pi-based Sonos controller that uses RFID tags to trigger music playback. Tap a
card to play an album; tap a stop card to pause.

## Architecture

A **server** (Flask + SQLite, Docker) manages tag-to-URI mappings via a web UI and JSON API.
A **client** (Raspberry Pi with RFID hardware) reads tags, looks up URIs in a local cache,
and plays directly on Sonos. The critical path — tap card, play music — works without the
server. See [ARCHITECTURE.md](ARCHITECTURE.md) for full design details.

```
           SERVER (Flask :3000)                    CLIENT (Pi)
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
2. Open the web UI at `http://tontraeger.local:3000`
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
| `PI_USER` | deploy targets | `pi` | User on the Pi for running the service |
| `PI_GROUP` | deploy targets | `pi` | Group on the Pi for running the service |
| `PI_UV_BIN_DIR` | client | `/home/pi/.local/bin` | Path to the `uv` binary on the Pi |
| `TONTRAEGER_SERVER` | client | `http://tontraeger.local:3000` | Server URL |
| `TONTRAEGER_CACHE_PATH` | client | `/home/pi/tontraeger/client/mappings.json` | Local mapping cache path on Pi |

## Development

Run `make check` to lint, typecheck, and test everything. Run `make web` to start the
Flask server locally (without Docker). See `make help` for all targets.
