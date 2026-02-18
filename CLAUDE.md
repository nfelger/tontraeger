# CLAUDE.md

Raspberry Pi-based Sonos controller. RFID tags trigger music playback. Monorepo with two components: a Flask server for mapping management and a Raspberry Pi client for tag reading + Sonos control.

## Project Structure

```
server/   Flask web UI + JSON API + SQLite (own pyproject.toml, Makefile, uv.lock)
client/   RFID reader + local cache + Sonos playback (own pyproject.toml, Makefile, uv.lock)
```

Dependencies managed with **uv**.

## Verifying Changes

```bash
make check                  # IMPORTANT: run this before committing (lint + typecheck + test)
make test                   # all tests
make test-server            # server tests only
make test-client            # client tests only
make lint                   # ruff check
make format                 # ruff format
make typecheck              # mypy
```

Single test file: `cd server && uv run pytest tests/test_web.py`
Single test: `cd server && uv run pytest tests/test_web.py::test_add_mapping`

## Architecture Essentials

The critical path (tap card, play music) has **no server dependency**. The client uses a local cache for O(1) lookup and plays directly on Sonos. The server only manages mappings via the web UI. Do not introduce server dependencies on the playback path.

- `"STOP"` is a special `media_uri` value that pauses playback instead of playing.
- Spotify share links (`https://`) go through SoCo's `ShareLinkPlugin`; all other URIs use `add_uri_to_queue`.
