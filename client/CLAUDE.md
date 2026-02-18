# Client

Runs on Raspberry Pi. Polls server for mappings, reads RFID tags, plays on Sonos. asyncio event loop with signal handling. In-memory dict backed by `mappings.json` on disk. 5-second debounce on duplicate tag reads.

## Gotchas

- **Conditional import**: `rfid_reader.py` is imported inside `main()` in `main.py`, not at the top level. `RPi.GPIO` crashes on import on non-Linux platforms — this would break tests and development.
- **Platform-guarded deps**: `mfrc522` and `RPi.GPIO` are Linux-only (`sys_platform == 'linux'` in `pyproject.toml`). Tests run on any platform.
- **Test fakes over mocks**: Tests use simple fakes (`DummySonosAPI`) rather than `unittest.mock`. The interfaces are small enough that fakes are clearer. Follow this pattern.
- **Atomic file writes**: `cache.py` uses temp file + `os.replace`. A crash during a direct write would corrupt the cache and leave the client unable to play until the next successful server sync.
