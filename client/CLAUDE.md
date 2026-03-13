# Client

Runs on Raspberry Pi. Polls server for mappings, detects NFC tags via a C daemon, plays on Sonos. In-memory dict backed by `mappings.json` on disk.

## Architecture

A C daemon (`nfc-daemon/main.c`) talks to the PN532 NFC reader via libnfc. Python spawns it as a child process and reads line-based events from its stdout:

- `PRESENT <uid>` — tag placed on reader, triggers playback
- `REMOVED <uid>` — tag removed, pauses playback

UIDs are colon-separated lowercase hex (e.g. `04:ab:cd:12:34:56:78`).

## Gotchas

- **Daemon child cleanup**: `control.py` tells Linux to auto-kill the daemon child if the Python parent crashes. This uses a Linux-only system call, guarded with `sys.platform == "linux"` so it doesn't break tests on macOS.
- **Test fakes over mocks**: Tests use simple fakes (`DummySonosAPI`, `DummySync`) rather than `unittest.mock`. The interfaces are small enough that fakes are clearer. Follow this pattern.
- **Atomic file writes**: `cache.py` uses temp file + `os.replace`. A crash during a direct write would corrupt the cache and leave the client unable to play until the next successful server sync.
- **`os._exit(0)`**: Used in `main.py` as a safety net. Sonos and HTTP calls run in background threads that may still be blocked on network I/O during shutdown, preventing clean exit.
