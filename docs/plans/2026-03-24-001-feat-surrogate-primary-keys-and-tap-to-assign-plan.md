---
title: "feat: Surrogate primary keys for mappings + tap-to-assign"
type: feat
status: completed
date: 2026-03-24
origin: docs/brainstorms/2026-03-24-proper-mapping-primary-keys-brainstorm.md
---

# feat: Surrogate primary keys for mappings + tap-to-assign

## Overview

Replace `tag_uid TEXT PRIMARY KEY` in the `tags` table with `id INTEGER PRIMARY KEY AUTOINCREMENT`. Make `tag_uid` a nullable, editable `TEXT UNIQUE` field. Change all URL routes from `/mappings/<tag_uid>/...` to `/mappings/<int:id>/...`. Add a tap-to-assign feature: an "Assign tag" button in the edit form that polls for scanned NFC tags via htmx.

## Problem Statement / Motivation

Mappings are created before physical NFC tokens are printed and programmed. The current schema forces a tag UID to exist from the start, making it impossible to pre-create mappings and assign tags later. Decoupling identity from hardware assignment lets the user create mappings in advance and assign tags when ready (see brainstorm: `docs/brainstorms/2026-03-24-proper-mapping-primary-keys-brainstorm.md`).

## Proposed Solution

Five-phase implementation: schema + TagMapper first, then routes + templates, then API compatibility, then tap-to-assign, then tests.

## Technical Approach

### Design Decisions

These decisions were made during brainstorming and SpecFlow analysis:

| Decision | Choice | Rationale |
|---|---|---|
| Return type | 6-tuple `(id, tag_uid, media_uri, name, shuffle, has_image)` | Consistent with existing tuple pattern; `id` prepended |
| `insert_mapping` | Split into `create_mapping` (INSERT) + `update_mapping` (UPDATE by id) | Upsert-on-UID pattern no longer works with nullable UID (see brainstorm) |
| CSS element IDs | Derived from integer `id`, not `tag_uid` | Eliminates colon-escaping problem entirely |
| `compute_hash` / ETag | Computed only over mappings with non-null `tag_uid` | Prevents unnecessary cache invalidation on client when unassigned mappings change |
| API response `id` field | Not included | Client has no use for it; minimizes contract change |
| Pending-tag response | `{"tag_uid": "..."}` or HTTP 204 (no content) | Simple contract; uniqueness checked at save time, not poll time |
| Polling interval | Every 1 second | Fast enough for good UX, light enough for a Pi |
| Polling timeout | None — stops on cancel, save, or tag arrival | htmx polling stops when element is removed from DOM |
| Clearing UID (assigned → unassigned) | Allowed without confirmation | Explicit user action (open edit, clear field, save) |
| UID format validation | None beyond uniqueness | Matches current behavior |
| "Use" button on edit form | Not in scope | Tap-to-assign is the mechanism for edit forms |

### TDD Approach

Each phase follows red/green TDD: write failing tests first, then implement the minimum code to make them pass.

### Implementation Phases

#### Phase 1: Schema Migration + TagMapper

**Goal:** New table schema, updated Python data layer. No UI changes yet.

**Red (tests first):** Write tests in `test_tag_mapper.py` for the new API surface before changing `TagMapper`:
- `test_create_mapping_returns_id` — `create_mapping()` returns an integer ID
- `test_create_mapping_without_uid` — `tag_uid=None` creates a row with NULL UID
- `test_create_mapping_with_uid` — `tag_uid="04:ab:..."` creates a row with that UID
- `test_get_mapping_by_id` — returns 6-tuple `(id, tag_uid, ...)`
- `test_get_all_mappings_returns_6_tuples` — each row includes `id` as first element
- `test_update_mapping_by_id` — changes fields on existing row by `id`
- `test_update_mapping_duplicate_uid_raises` — `IntegrityError` on UID conflict
- `test_delete_mapping_by_id` — removes row by `id`
- `test_upsert_image_by_id` — stores image by `id`
- `test_get_mappings_with_images_by_id` — accepts list of integer IDs
- `test_migration_from_old_schema` — create old-format table, init `TagMapper`, verify data intact

**Green (implementation):**

**1a. Table recreation in `_init_db()`** (`tag_mapper.py`)

SQLite does not support adding a column with `PRIMARY KEY` or changing the primary key. Use the table-recreation pattern:

```sql
-- Only run if 'id' column does not exist (migration guard)
CREATE TABLE tags_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_uid TEXT UNIQUE,
    media_uri TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    shuffle INTEGER NOT NULL DEFAULT 0,
    image_data TEXT NOT NULL DEFAULT ''
);
INSERT INTO tags_new (tag_uid, media_uri, name, shuffle, image_data)
    SELECT tag_uid, media_uri, name, shuffle, image_data FROM tags
    ORDER BY tag_uid;
DROP TABLE tags;
ALTER TABLE tags_new RENAME TO tags;
```

Migration guard: check if `id` column exists before running. Use `PRAGMA table_info(tags)` and look for an `id` column. If present, skip migration. Keep the existing `ALTER TABLE ADD COLUMN` guards for `shuffle` and `image_data` — they run BEFORE the recreation migration (for databases that predate those columns but haven't been migrated to the new PK scheme yet).

Per institutional learning: `CREATE TABLE` is the canonical schema. The base DDL and migration must agree.

**1b. TagMapper method changes** (`tag_mapper.py`)

| Current method | New method | Key change |
|---|---|---|
| `insert_mapping(tag_uid, media_uri, name, shuffle)` | `create_mapping(media_uri, name, shuffle, tag_uid=None) -> int` | INSERT, returns `id`. `tag_uid` optional. |
| (same, used for edit) | `update_mapping(id, media_uri, name, shuffle, tag_uid=None)` | UPDATE by `id`. Raises `IntegrityError` on UID conflict. |
| `get_mapping(tag_uid)` | `get_mapping(id: int)` | WHERE id = ? |
| `get_all_mappings()` | `get_all_mappings()` | Returns 6-tuples. `ORDER BY id`. |
| `get_uri(tag_uid)` | `get_uri(tag_uid)` | Unchanged — runtime playback lookup stays UID-keyed |
| `delete_mapping(tag_uid)` | `delete_mapping(id: int)` | WHERE id = ? |
| `upsert_image(tag_uid, image_data)` | `upsert_image(id: int, image_data)` | WHERE id = ? |
| `get_mappings_with_images(uids)` | `get_mappings_with_images(ids: list[int])` | WHERE id IN (?) |
| `compute_hash(mappings)` | `compute_hash(mappings)` | Same serialization (tag_uid, media_uri, name, shuffle). Caller filters out null-UID mappings before calling. |
| `content_hash` | Remove or update | The `api_mappings` route should compute the hash over the filtered set directly, not use a property that hashes everything. |

Return type of `get_mapping` and `get_all_mappings`: `tuple[int, str | None, str, str, bool, bool]` → `(id, tag_uid, media_uri, name, shuffle, has_image)`.

#### Phase 2: Routes + HTML Templates

**Goal:** All routes use `<int:id>`, templates updated, add/edit forms reflect new schema.

**Red (tests first):** Write/update tests in `test_web.py` for the new routes before changing `web.py`:
- Update all existing route tests: paths change from `/mappings/<uid>/...` to `/mappings/<id>/...`
- `test_add_mapping_without_uid` — POST without `tag_uid`, verify mapping created and visible
- `test_add_mapping_with_uid` — POST with `tag_uid`, same as before but verify routes use `id`
- `test_edit_mapping_change_uid` — POST new `tag_uid` in edit form
- `test_edit_mapping_clear_uid` — POST empty `tag_uid`, verify NULL
- `test_edit_mapping_duplicate_uid_error` — POST duplicate `tag_uid`, verify error in response HTML
- `test_card_view_unassigned_shows_indicator` — verify "No tag" indicator in card HTML
- `test_print_uses_id_params` — `/print?id=1&id=2` instead of `tag_uid=...`

**Green (implementation):**

**2a. Route handler updates** (`web.py`)

| Current route | New route | Handler changes |
|---|---|---|
| `POST /mappings` (`add_mapping`) | Same URL | Call `create_mapping()` instead of `insert_mapping()`. `tag_uid` optional in form data. |
| `GET /mappings/<tag_uid>/edit-form` | `GET /mappings/<int:id>/edit-form` | `mapper.get_mapping(id)` |
| `GET /mappings/<tag_uid>/card` | `GET /mappings/<int:id>/card` | `mapper.get_mapping(id)` |
| `POST /mappings/<tag_uid>/edit` | `POST /mappings/<int:id>/edit` | Call `update_mapping(id, ...)`. Read `tag_uid` from form. Catch `IntegrityError` → re-render edit form with error "This tag UID is already assigned to another mapping." (per learning: return HTTP 200 with error in re-rendered form). |
| `POST /mappings/<tag_uid>/delete` | `POST /mappings/<int:id>/delete` | `mapper.delete_mapping(id)` |
| `POST /mappings/<tag_uid>/image` | `POST /mappings/<int:id>/image` | `mapper.upsert_image(id, ...)` |
| `GET /mappings/<tag_uid>/image` | `GET /mappings/<int:id>/image` | `mapper.get_mappings_with_images([id])` |
| `GET /print?tag_uid=...` | `GET /print?id=...` | `request.args.getlist("id", type=int)` |

**2b. Template function updates** (`web.py`)

`_card_view_html(id, tag_uid, media_uri, name, shuffle, has_image)`:
- CSS id: `f"card-{id}"` (no colon escaping needed — integer IDs are clean)
- Print checkbox: `$store.printMode.selected` uses integer `id` (via `{id}` in JS)
- Display: show "No tag assigned" indicator when `tag_uid is None`
- Edit button: `url_for("edit_form", id=id)`
- Thumbnail: `url_for("get_image", id=id)` with `f"thumb-{id}"`

`_card_edit_html(id, tag_uid, media_uri, name, shuffle, has_image, error=None)`:
- Tag UID field: **enabled** `<input type="text" name="tag_uid" value="{tag_uid or ''}">`
- "Assign tag" button (see Phase 4)
- All `url_for()` calls use `id=id`
- Error display for duplicate UID: show `error` string if present
- Form: `form="edit-form-{id}"`

`_card_thumb_html(id, has_image)` — use `id` for all CSS ids and URLs.

Add form (`PAGE_TEMPLATE`):
- Remove `required` from `tag_uid` input
- Keep the `x-ref="tagUid"` for the "Use" button on unknown tags

Print button JS: `Array.from($store.printMode.selected).map(i => 'id=' + i).join('&')`

Print template: `url_for('get_image', id=mapping_id)` instead of `tag_uid=uid`.

#### Phase 3: API + Hash (Client Compatibility)

**Goal:** Client sync works unchanged. Unassigned mappings excluded from API.

**Red (tests first):**
- `test_api_mappings_excludes_unassigned` — create mapping without UID, verify absent from `/api/mappings`
- `test_api_mappings_includes_assigned` — create mapping with UID, verify present
- `test_api_mappings_etag_stable_on_unassigned_change` — modify an unassigned mapping, verify ETag unchanged
- `test_api_mappings_response_shape_unchanged` — verify response has `tag_uid`, `media_uri`, `name`, `shuffle`, `has_image` — no `id`

**Green (implementation):**

**3a. `GET /api/mappings`** (`web.py`):
```python
all_mappings = mapper.get_all_mappings()
synced = [(id, t, u, n, s, hi) for id, t, u, n, s, hi in all_mappings if t is not None]
etag = mapper.compute_hash(synced)
# ... response uses synced list, serializes without id field
```

Response shape unchanged: `{"tag_uid": t, "media_uri": u, "name": n, "shuffle": s, "has_image": hi}`. No `id` field.

**3b. No client changes needed.** Per brainstorm: client `cache.py`, `sync.py`, `control.py` are unaffected.

#### Phase 4: Tap-to-Assign

**Goal:** "Assign tag" button in edit form, polls for scanned NFC tags.

**Red (tests first):**
- `test_unknown_tag_inbox_get_since` — report a tag, query with `since` before → returns it; query with `since` after → returns None
- `test_pending_tag_returns_uid` — POST unknown tag, GET `/api/pending-tag?since=<before>` → 200 with `tag_uid`
- `test_pending_tag_no_result` — GET `/api/pending-tag?since=<now>` → 204
- `test_pending_tag_missing_since` — GET `/api/pending-tag` without `since` → 400

**Green (implementation):**

**4a. `UnknownTagInbox` extension** (`web.py`):

Add method:
```python
def get_since(self, since_iso: str) -> dict | None:
    """Return the most recently seen unknown tag after `since_iso`, or None."""
    for entry in reversed(self._tags.values()):
        if entry["last_seen"] > since_iso:
            return entry
    return None
```

**4b. New endpoint: `GET /api/pending-tag`** (`web.py`):
```python
@app.route("/api/pending-tag")
def api_pending_tag() -> Response:
    since = request.args.get("since", "")
    if not since:
        return Response(status=400)
    entry = unknown_tags.get_since(since)
    if entry is None:
        return Response(status=204)
    return jsonify(tag_uid=entry["tag_uid"])
```

**4c. Edit form: "Assign tag" button + polling**

In `_card_edit_html`, below the tag_uid input:

```html
<button type="button"
    x-data="{ waiting: false, since: '' }"
    @click="waiting = true; since = new Date().toISOString()"
    x-show="!waiting"
>
    Assign tag
</button>
<div x-show="waiting">
    <span>Waiting for tag scan...</span>
    <div hx-get="/api/pending-tag"
         hx-trigger="load, every 1s"
         hx-vals='js:{"since": since}'
         hx-target="this"
         hx-swap="none"
         ...>
    </div>
    <button type="button" @click="waiting = false">Cancel</button>
</div>
```

The htmx polling + Alpine integration needs careful design. Two options:

**Option A — htmx response handler with `HX-Trigger` header:**
The server returns `HX-Trigger: tagAssigned` header with the UID in a custom event. Alpine listens for it via `@tagAssigned.window` and fills the input. This avoids mixing htmx swap with Alpine state.

**Option B — Server returns an HTML fragment that fills the input:**
The pending-tag endpoint returns an `<input>` fragment that replaces the UID field directly. Simpler server-side but couples the API endpoint to HTML rendering.

**Recommendation: Option A** — cleaner separation. The server returns JSON with `HX-Trigger` response header. Alpine handles state.

Implementation:
1. When tag found, endpoint returns: `Response(status=204, headers={"HX-Trigger": json.dumps({"tagAssigned": {"tag_uid": uid}})})`
2. Edit form listens: `@tag-assigned.window="$refs.tagUidInput.value = $event.detail.tag_uid; waiting = false"`
3. When no tag: return `Response(status=204)` (no trigger header) — htmx continues polling

**4d. Duplicate UID at save time:**

In the `edit_mapping` route:
```python
try:
    mapper.update_mapping(id, media_uri, name, shuffle, tag_uid=tag_uid or None)
except sqlite3.IntegrityError:
    mapping = mapper.get_mapping(id)
    return _card_edit_html(*mapping, error="This tag UID is already assigned to another mapping.")
```

Per institutional learning: validation errors return HTTP 200 with re-rendered form including error message.

#### Phase 5: Refactor pass

After all phases are green, review for cleanup opportunities: remove dead code (`css_id` filter if unused), simplify any over-complicated helpers, verify no leftover `tag_uid` path segments in routes.

## System-Wide Impact

- **Client playback path**: Unaffected. Only non-null UID mappings appear in the API. Client code unchanged.
- **API contract**: Response shape unchanged. Only filtering behavior changes (excludes null-UID rows).
- **URL bookmarks**: All `/mappings/<tag_uid>/...` URLs break. Unavoidable — the URL scheme changes fundamentally. No redirect needed (internal tool, single user).
- **State transitions**: unassigned → assigned (edit + set UID), assigned → reassigned (edit + change UID), assigned → unassigned (edit + clear UID). All go through the same `update_mapping` method.

## Acceptance Criteria

- [x] Existing mappings survive migration with auto-assigned integer IDs
- [x] Fresh database creates table with new schema
- [x] Add form works without tag UID (creates unassigned mapping)
- [x] Add form works with tag UID (creates assigned mapping, same as before)
- [x] Unassigned mappings visible in list with "No tag" indicator
- [x] Edit form shows tag UID as editable text field
- [x] Saving a duplicate UID shows error, does not overwrite
- [x] "Assign tag" button polls and auto-fills UID on tag scan
- [x] Cancelling tap-to-assign stops polling
- [x] `/api/mappings` excludes unassigned mappings
- [x] `/api/mappings` ETag stable when only unassigned mappings change
- [x] Print mode uses integer IDs
- [x] Client playback unaffected (no client code changes)
- [x] `make check` passes

## Dependencies & Risks

- **Risk: Migration data loss.** The table-recreation pattern is destructive. If it fails mid-way, data is lost. Mitigation: wrap in a transaction, test with real data first.
- **Risk: Missed tuple unpacking site.** Every `*mapping` or positional unpack must be updated. Mitigation: type checking (`make check` runs mypy) will catch wrong tuple sizes.
- **Risk: htmx + Alpine interaction for tap-to-assign.** The `HX-Trigger` event approach needs testing. Per learning: Alpine directives on htmx-swapped content work if inside an existing `x-data` scope.

## Sources & References

- **Origin brainstorm:** [docs/brainstorms/2026-03-24-proper-mapping-primary-keys-brainstorm.md](docs/brainstorms/2026-03-24-proper-mapping-primary-keys-brainstorm.md) — Key decisions: integer PK, nullable UID, tap-to-assign via polling, warn-and-reject on duplicate
- **Institutional learnings:**
  - [Shuffle feature review patterns](docs/solutions/logic-errors/shuffle-feature-review-patterns.md) — CREATE TABLE and ALTER TABLE must agree; API backward compat with `.get()`
  - [Alpine-to-htmx migration pattern](docs/solutions/ui-bugs/alpine-to-htmx-migration-pattern.md) — htmx polling pattern, fragment endpoints
  - [Pure htmx inline editing](docs/solutions/ui-bugs/pure-htmx-inline-edit-without-alpine-state.md) — Validation errors return HTTP 200 with re-rendered form
  - [htmx CSS selector colons](docs/solutions/ui-bugs/htmx-css-selector-colons-in-ids.md) — Colon problem eliminated by switching to integer IDs
- **Key files:** `tag_mapper.py`, `web.py` (routes + inline templates), `test_tag_mapper.py`, `test_web.py`
