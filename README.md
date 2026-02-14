# SpotiBox

A Raspberry Pi-based Sonos controller that uses RFID tags to control music playback. Simply tap an RFID card to play a specific resource on your Sonos speaker or stop playback.

## Overview

SpotiBox bridges the physical and digital worlds by mapping RFID tags to content on Sonos speakers. Each tag can be associated with a different media resource (albums, radio stations, etc.), allowing for a tangible, touch-based music control experience. Perfect for creating a music box for kids, quick access to favourite content, or just a fun IoT project.

## Features

- **RFID-Controlled Playback**: Tap an RFID tag to instantly play its associated resource on Sonos
- **Stop Command Support**: Designate a specific tag to pause playback
- **Tag Debouncing**: Prevents repeated triggers from the same tag within 5 seconds
- **Async Architecture**: Non-blocking event loop for responsive tag reading
- **Local Sonos Control**: Direct control of Sonos speakers via SoCo's `play_uri`
- **Persistent Mappings**: SQLite database stores tag-to-content associations
- **Testing Suite**: Comprehensive unit tests for core functionality

## Requirements

- **Raspberry Pi** (any model with GPIO pins and wifi)
- **MFRC522 RFID Reader** (RC522 module)
- **RFID Tags/Cards** (13.56 MHz compatible)
- Jumper wires for connections
- Sonos speaker on the same network

## Installation

### On Development Machine

```bash
# Install uv (optional but recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install
uv pip install -e .
```

### On Raspberry Pi

See `INSTALL.md`.

### Sonos Configuration

1. Ensure your Sonos speaker is on the same network as your Raspberry Pi
2. Note the exact name of your Sonos speaker (check the Sonos app)
3. Create a `.env` file in the project root:
   ```env
   SONOS_SPEAKER_NAME=Living Room
   ```
   Replace "Living Room" with your actual Sonos speaker name

To find your speaker names programmatically:
```python
import soco
speakers = soco.discover()
for s in speakers:
    print(s.player_name)
```

## Usage

### Main Controller

Run the continuous RFID monitoring service:

```bash
python -m spotibox.control
```

This starts the main loop that:
- Continuously listens for RFID tags
- Maps tag IDs to media URIs
- Controls playback on your Sonos speaker

Press `Ctrl+C` to stop.

### Utility Scripts

**Read an RFID tag ID**:
```bash
python -m spotibox.read_rfid_tag_id
```


### Managing Tag Mappings

Tag-to-URI mappings are stored in `tags.db`. To add or modify mappings, you can:

1. Use the `TagMapper` class in your own scripts:
   ```python
   from spotibox.tag_mapper import TagMapper

   mapper = TagMapper()
   # Music service share links
   mapper.insert_mapping("123456789", "https://open.spotify.com/album/YOUR_ALBUM_ID")
   # Native Sonos URIs (e.g. TuneIn radio)
   mapper.insert_mapping("246813579", "x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0")
   mapper.insert_mapping("987654321", "STOP")  # Special stop command
   ```

2. Directly modify the SQLite database using any SQLite client

## Project Structure

```
spotibox/
├── config.py              # Configuration and environment variables
├── control.py             # Main controller and async event loop
├── tag_mapper.py          # SQLite-backed tag-to-URI mapping
├── rfid_reader.py         # RFID tag reading interface
├── sonos_api.py           # Sonos speaker control wrapper
└── read_rfid_tag_id.py    # Utility to read tag IDs

tests/
├── test_control.py        # Controller tests
├── test_tag_mapper.py     # Database mapping tests
└── test_sonos_api.py      # Sonos API tests

tags.db                    # SQLite database (auto-created)
sync_to_pi.sh              # Deployment script for Raspberry Pi
```

## Architecture

### Core Components

1. **RFIDReader** (`rfid_reader.py`)
   - Interfaces with MFRC522 hardware via `SimpleMFRC522`
   - Blocks until a tag is detected, returns tag ID as string
   - Handles GPIO cleanup on shutdown

2. **TagMapper** (`tag_mapper.py`)
   - SQLite-backed persistence layer
   - Maps RFID tag UIDs to media URIs
   - Supports special "STOP" command

3. **SonosAPI** (`sonos_api.py`)
   - Wraps SoCo library for Sonos control
   - Discovers and controls specified Sonos speaker
   - Uses `play_uri` to support any SoCo-compatible media URI
   - Provides `play_uri()` and `stop_playback()` methods

4. **PlaybackController** (`control.py`)
   - Orchestrates RFID reading and Sonos control
   - Implements tag debouncing (5-second window)
   - Async event loop for non-blocking operation

### Data Flow

```
RFID Tag → RFIDReader → PlaybackController → TagMapper → SonosAPI → Sonos Speaker
```

1. User taps RFID tag
2. RFIDReader detects tag and returns UID
3. PlaybackController checks debouncing logic
4. TagMapper looks up media URI for tag UID
5. SonosAPI starts playback on Sonos speaker via `play_uri`

## Development

### Running Tests

```bash
pytest
```

### Code Quality

The project uses:
- **Ruff**: Fast Python linter and formatter
- **MyPy**: Static type checking
- **Pytest**: Testing framework

Run quality checks:
```bash
ruff check .        # Lint code
ruff format .       # Format code
mypy spotibox/      # Type checking
```
