# Client

Runs on Raspberry Pi. Polls server for mappings, reads RFID tags, plays on Sonos. asyncio event loop with signal handling. In-memory dict backed by `mappings.json` on disk. 5-second debounce on duplicate tag reads.

## Key Files

- `tontraeger_client/main.py` — Entry point: wires components, asyncio event loop, signal handlers
- `tontraeger_client/control.py` — `PlaybackController` (tag lookup + play/stop) and `main_loop` (RFID reading with debounce)
- `tontraeger_client/cache.py` — `MappingCache`: in-memory dict + atomic JSON persistence (temp file + `os.replace`)
- `tontraeger_client/sync.py` — `MappingSync`: polls `GET /api/mappings` every 10s with `If-None-Match` ETag, reports unknown tags (fire-and-forget)
- `tontraeger_client/rfid_reader.py` — MFRC522 hardware interface (SPI/GPIO)

## Commands

```bash
uv run pytest                               # all client tests
uv run pytest tests/test_control.py -k test_handle_tag_plays_uri   # single test
uv run ruff check tontraeger_client/        # lint
uv run mypy tontraeger_client/              # typecheck
```

## Gotchas

- **Conditional import**: `rfid_reader.py` is imported inside `main()` in `main.py` to avoid importing `RPi.GPIO` on non-Pi machines. Do not move to a top-level import.
- **Platform-guarded deps**: `mfrc522` and `RPi.GPIO` are Linux-only (`sys_platform == 'linux'` in `pyproject.toml`). Tests run on any platform.
- **Test fakes over mocks**: Tests use simple fakes like `DummySonosAPI` rather than `unittest.mock`. Follow this pattern for new tests.
- **Atomic file writes**: `cache.py` uses temp file + `os.replace` for persistence. Do not simplify to direct writes.
