# tontraeger Installation

## Architecture Overview

tontraeger uses a client-server architecture:
- **Server**: Flask web UI + JSON API, runs in a Docker container (any machine on your LAN)
- **Client**: RFID reader + Sonos playback, runs on a Raspberry Pi via systemd

## Server Setup

### Prerequisites
- Docker and Docker Compose

### Start the server

```bash
# From the repository root:
make docker-up

# Or manually:
docker compose up -d
```

The server listens on port 5000. The SQLite database is persisted in a Docker volume.

Configure via environment variables (or a `.env` file in the repo root):
- `SONOS_SPEAKER_NAME` — default Sonos speaker name (default: `Wohnzimmer`)

### Migrating an existing `tags.db`

If you have an existing `tags.db` from a previous single-Pi setup:

```bash
# Find the Docker volume path:
docker volume inspect tontraeger_server-data --format '{{ .Mountpoint }}'

# Copy the database into the volume:
sudo cp tags.db "$(docker volume inspect tontraeger_server-data --format '{{ .Mountpoint }}')/tags.db"

# Restart the server to pick up the database:
make docker-down && make docker-up
```

No schema changes are needed — the existing database works as-is.

## Client Setup (Raspberry Pi)

### Hardware
- Wire up the RFID-RC522 reader as described here:
  https://tutorials-raspberrypi.de/raspberry-pi-rfid-rc522-tueroeffner-nfc/
  (wiring only — don't follow the rest of the tutorial)

### Pi configuration
```bash
# Enable SPI interface:
sudo raspi-config   # → Interface Options → SPI → Enable
sudo reboot

# Install Python headers:
sudo apt update && sudo apt install python3.11-dev

# Install uv:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Deploy the client

```bash
# From your development machine:
make deploy-client

# Or manually:
rsync -av --filter=':- .gitignore' --exclude='tests/' \
    client/ pi@tontraeger.local:/home/pi/tontraeger/client/
```

### Install the systemd service

On the Pi:

```bash
# Copy the service file:
sudo cp /home/pi/tontraeger/client/tontraeger-client.service /etc/systemd/system/

# Edit environment variables if needed:
sudo systemctl edit tontraeger-client
# Override SONOS_SPEAKER_NAME, TONTRAEGER_SERVER, etc.

# Enable and start:
sudo systemctl daemon-reload
sudo systemctl enable tontraeger-client
sudo systemctl start tontraeger-client

# Check status:
sudo systemctl status tontraeger-client
journalctl -u tontraeger-client -f
```

### Client environment variables
- `SONOS_SPEAKER_NAME` — Sonos speaker to play on (default: `Wohnzimmer`)
- `TONTRAEGER_SERVER` — Server URL (default: `http://tontraeger.local:5000`)
- `TONTRAEGER_CACHE_PATH` — Local mapping cache file (default: `mappings.json`)
