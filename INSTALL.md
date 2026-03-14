# tontraeger Installation

## Architecture Overview

tontraeger uses a client-server architecture:
- **Server**: Flask web UI + JSON API, runs in a Docker container (any machine on your LAN)
- **Client**: NFC reader + Sonos playback, runs on a Raspberry Pi via systemd

## Server Setup

### Prerequisites
- Docker and Docker Compose

### Configure

Copy `.env.sample` to `.env` and adjust values:

```bash
cp .env.sample .env
```

Key server variable:
- `SONOS_SPEAKER_NAME` — default Sonos speaker name (default: `Wohnzimmer`)

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
# Find the Docker volume path:
docker volume inspect tontraeger_server-data --format '{{ .Mountpoint }}'

# Copy the database into the volume:
sudo cp tags.db "$(docker volume inspect tontraeger_server-data --format '{{ .Mountpoint }}')/tags.db"

# Restart the server to pick up the database:
make docker-down && make run-server
```

No schema changes are needed — the existing database works as-is.

## Client Setup (Raspberry Pi)

### Hardware

Wire up the PN532 NFC reader to the Raspberry Pi via UART:

| PN532 pin | Pi pin | Notes |
|-----------|--------|-------|
| VCC | Pin 2 (5V) | **Must be 5V, not 3.3V** |
| GND | Pin 6 (GND) | |
| SDA (= TX in UART mode) | Pin 10 (GPIO15 / RXD) | PN532 TX → Pi RX |
| SCL (= RX in UART mode) | Pin 8 (GPIO14 / TXD) | PN532 RX → Pi TX |

Set the PN532 DIP switches to UART mode: **SW1 = OFF, SW2 = OFF**.

Note: The SDA/SCL pins on the PN532 board double as UART TX/RX when the DIP switches
are set to UART mode. TX and RX must be cross-wired (PN532 TX → Pi RX and vice versa).

### Pi configuration
```bash
# Disable serial console, enable serial hardware:
sudo raspi-config
#   → Interface Options → Serial Port
#   → "Login shell over serial?" → No
#   → "Serial port hardware enabled?" → Yes
sudo reboot

# Install dependencies:
sudo apt update && sudo apt install libnfc-dev libnfc-bin make

# Configure libnfc for UART:
sudo tee /etc/nfc/libnfc.conf > /dev/null << 'EOF'
allow_autoscan = false
device.name = "PN532"
device.connstring = "pn532_uart:/dev/serial0"
EOF

# Verify the PN532 is detected:
nfc-list             # should show "NFC device: PN532 ... opened"

# Install uv:
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Configure and sync the client

Edit `.env` on your development machine with the client variables:
- `PI_HOST` — SSH target for the Pi (default: `pi@tontraeger.local`)
- `PI_DIR` — directory on the Pi (default: `/home/pi/tontraeger`)
- `PI_USER` — user on the Pi for running the service (default: `pi`)
- `PI_GROUP` — group on the Pi for running the service (default: `pi`)
- `PI_UV_BIN_DIR` — path to the `uv` binary on the Pi (default: `/home/pi/.local/bin`)
- `TONTRAEGER_SERVER` — server URL (default: `http://tontraeger.local:3000`)
- `SONOS_SPEAKER_NAME` — Sonos speaker to play on (default: `Wohnzimmer`)
- `TONTRAEGER_CACHE_PATH` — local mapping cache on the Pi
- `NFC_DAEMON_PATH` — path to the NFC daemon binary (default: `/usr/local/bin/nfc-daemon`)

Then sync the client code to the Pi:

```bash
make sync-client
```

### Install the systemd service

From your development machine, run:

```bash
make install-client-service
```

This generates the service file with values from `.env`, installs it on the Pi,
and enables it to start on boot. To start it immediately:

```bash
ssh pi@tontraeger.local 'sudo systemctl start tontraeger-client'
```

To check status:

```bash
ssh pi@tontraeger.local 'sudo systemctl status tontraeger-client'
ssh pi@tontraeger.local 'journalctl -u tontraeger-client -f'
```
