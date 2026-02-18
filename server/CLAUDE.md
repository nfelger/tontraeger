# Server

Single-process Flask app on port 5000. SQLite source of truth. ETag (SHA-256 content hash) for conditional sync with clients.

## Gotchas

- **Inline HTML template**: The entire UI is a single `PAGE_TEMPLATE` string in `web.py`, not a separate template file. This keeps the UI in one greppable location and avoids Flask template discovery configuration.
- **Schema migration**: `TagMapper._init_db()` runs `ALTER TABLE` and catches the error if the column already exists — supports databases created before the `name` column was added.
- **Module-level state in web.py**: `mapper`, `sonos`, and `unknown_tags` are module-level objects (the Flask app is module-level). Tests patch these directly (see `test_web.py` fixtures). Follow this pattern for new tests.
- **UnknownTagInbox**: In-memory only, max 20 entries, FIFO eviction. Persistence isn't needed because tags can simply be re-scanned.
- **Docker networking**: `network_mode: host` in docker-compose.yml is required — SSDP multicast for Sonos discovery doesn't traverse Docker's default bridge network.
