# Server

Single-process Flask app on port 5000. SQLite source of truth. ETag (SHA-256 content hash) for conditional sync with clients.

## Key Files

- `tontraeger_server/web.py` — All Flask routes, HTML template (single inline string with Alpine.js + htmx), `UnknownTagInbox`
- `tontraeger_server/tag_mapper.py` — SQLite CRUD + SHA-256 content hash for ETag
- `tontraeger_server/sonos_api.py` — Speaker discovery via `soco.discover()` and playback control

## Commands

```bash
uv run pytest                             # all server tests
uv run pytest tests/test_web.py::test_add_mapping   # single test
uv run ruff check .                       # lint
uv run mypy tontraeger_server/            # typecheck
```

## Gotchas

- **Inline HTML template**: The entire UI is a single `PAGE_TEMPLATE` string in `web.py`, not a separate template file. Keep it that way.
- **Schema migration**: `TagMapper._init_db()` runs `ALTER TABLE` and catches the error if the column exists. This is intentional backward compatibility, not a bug.
- **Module-level state in web.py**: `mapper`, `sonos`, and `unknown_tags` are module-level objects. Tests patch these directly (see `test_web.py` fixtures). Follow this pattern for new tests.
- **UnknownTagInbox**: In-memory only, max 20 entries, FIFO eviction. Data loss on restart is acceptable by design.
- **Docker networking**: `network_mode: host` in docker-compose.yml is required for SSDP multicast (Sonos speaker discovery).
