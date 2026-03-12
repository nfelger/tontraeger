# tontraeger Installation

## Architecture Overview

tontraeger uses a client-server architecture:
- **Server**: Flask web UI + JSON API, runs in a Docker container (any machine on your LAN)
- **Client**: NFC tag reader + Sonos playback, runs on a Raspberry Pi via systemd. A C daemon talks to the PN532 NFC reader via libnfc; Python reacts to tag events and controls the Sonos speaker.

## Server Setup

### Prerequisites
- Docker and Docker Compose

### Configure

Copy `server/.env.sample` to `server/.env` and adjust:

```bash
cp server/.env.sample server/.env
```

Key server variable:
- `SONOS_SPEAKER_NAME` — Sonos speaker to play on (default: `Wohnzimmer`)

### Start the server

```bash
make run-server
```

This builds the Docker image and starts the server. The server listens on port 3000.
The SQLite database is persisted in a Docker volume.

To stop: `make docker-down`

### Migrating an existing `tags.db`

If you have an existing `tags.db` from a previous single-Pi setup:

```bash
# Find the Docker volume (name depends on your compose project):
docker volume ls | grep server-data

# Copy the database into the volume:
sudo cp tags.db "$(docker volume inspect server_server-data --format '{{ .Mountpoint }}')/tags.db"

# Restart the server to pick up the database:
make docker-down && make run-server
```

No schema changes are needed — the existing database works as-is.

**Note:** Tag UIDs in the database use colon-separated lowercase hex format (e.g. `04:ab:cd:12:34:56:78`). If migrating from the old RC522-based setup (which used decimal integer UIDs), all tags must be re-scanned and re-registered.

## Client Setup (Raspberry Pi)

### Hardware

Wire up a PN532 NFC reader to the Raspberry Pi via I2C:
- SDA → GPIO 2 (pin 3)
- SCL → GPIO 3 (pin 5)
- VCC → 3.3V (pin 1)
- GND → GND (pin 6)

### Pi configuration

```bash
# Enable I2C interface:
sudo raspi-config   # → Interface Options → I2C → Enable
sudo reboot

# Install dependencies:
sudo apt update && sudo apt install libnfc-bin libnfc-dev make gcc

# Install uv:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify the NFC reader is detected:

```bash
nfc-list
# Should show: NFC device: PN532 board via I2C opened
```

### Configure and sync the client

**Root `.env`** — deploy variables used by the root Makefile to sync code to the Pi.
Copy `.env.sample` to `.env` and adjust:

```bash
cp .env.sample .env
```

- `PI_HOST` — SSH target for the Pi (default: `pi@tontraeger.local`)
- `PI_DIR` — directory on the Pi (default: `/home/pi/tontraeger`)
- `PI_USER` — user on the Pi for running the service (default: `pi`)
- `PI_GROUP` — group on the Pi for running the service (default: `pi`)
- `PI_UV_BIN_DIR` — path to the `uv` binary on the Pi (default: `/home/pi/.local/bin`)

**`client/.env`** — runtime variables loaded by the client on the Pi.
Copy `client/.env.sample` to `client/.env` and adjust:

```bash
cp client/.env.sample client/.env
```

- `TONTRAEGER_SERVER` — server URL (default: `http://tontraeger.local:3000`)
- `SONOS_SPEAKER_NAME` — Sonos speaker to play on (default: `Wohnzimmer`)
- `TONTRAEGER_CACHE_PATH` — local mapping cache (default: `mappings.json`)
- `NFC_DAEMON_PATH` — path to the NFC daemon binary (default: `/usr/local/bin/nfc-daemon`)

Then sync the client code to the Pi:

```bash
make sync-client
```

This rsyncs the code, compiles the NFC daemon on the Pi, installs the binary to `/usr/local/bin/`, and restarts the service.

### Install the systemd service

From your development machine, run:

```bash
make install-client-service
```

This generates the service file with values from `.env`, installs it on the Pi,
and enables and starts the service automatically.

To check status:

```bash
ssh pi@tontraeger.local 'sudo systemctl status tontraeger-client'
ssh pi@tontraeger.local 'journalctl -u tontraeger-client -f'
```
