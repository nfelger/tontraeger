---
title: "Shuffle Feature: Code Review Patterns and Fixes"
category: logic-errors
date: 2026-03-16
tags:
  - backward-compat
  - cache-sync
  - database-schema
  - jinja2-escaping
  - asyncio
  - testing
  - css
problem_type: multi-layer integration issues discovered during feature code review
components_affected:
  - client/tontraeger_client/cache.py
  - client/tontraeger_client/sonos_api.py
  - client/tests/test_cache.py
  - client/tests/test_sonos_api.py
  - server/tontraeger_server/tag_mapper.py
  - server/tontraeger_server/web.py
  - server/tests/test_web.py
severity: high
origin: docs/plans/2026-03-16-001-feat-shuffle-flag-mappings-plan.md
---

# Shuffle Feature: Code Review Patterns and Fixes

A code review of the shuffle flag feature surfaced 8 issues (1 P1, 4 P2, 3 P3) plus a UI defect. This document captures the patterns — most recur beyond this specific feature.

## Problem Summary

After implementing `shuffle: bool` across the server/client stack, code review found:

1. **P1**: `cache._parse()` used `m["shuffle"]` — silent cache wipe on first Pi deploy + sync loop crash on server rollback
2. **P2**: `CREATE TABLE` missing `shuffle` column — only in `ALTER TABLE`
3. **P2**: `FakeSoCo` missing `play_mode` attribute — shuffle behavior untested at Sonos API layer
4. **P2**: Flash messages double-encoded: `escape()` inside f-string + Jinja2 auto-escape
5. **P2**: No test for shuffle badge in HTML template; backward compat test deleted to hide bug #1
6. **P3**: Stale `ALTER TABLE name` migration block (column already in `CREATE TABLE`)
7. **P3**: `run_in_executor(None, fn, arg1, arg2)` — fragile positional arg passing
8. **UI**: Shuffle checkbox had no CSS — stretched flex row, raw browser styling

## Solution

### 1. Hard Key Access vs `.get()` in Cache Parser (P1 — Critical)

**Root cause:** `_parse()` used `m["shuffle"]` while the adjacent field used `m.get("name", "")`. When existing `mappings.json` files lacked `shuffle` (pre-deploy), `_load()` caught `KeyError` and silently emptied the entire cache. Worse: a server rollback would cause `update()` to propagate unhandled `KeyError` through `sync.poll()`, crashing the sync loop permanently.

The symptom was hidden: `test_load_from_file_without_name_field` was **deleted** instead of updated, concealing the regression.

```python
# Before — KeyError if key absent (breaks backward compat, crashes sync loop)
m["tag_uid"]: (m["media_uri"], m.get("name", ""), bool(m["shuffle"]))

# After — safe default, consistent with adjacent field
m["tag_uid"]: (m["media_uri"], m.get("name", ""), bool(m.get("shuffle", False)))
```

**Test restored:**
```python
def test_load_from_file_without_shuffle_field(cache_path):
    """Cache files written before the shuffle feature was added load cleanly."""
    data = [{"tag_uid": "x1", "media_uri": "uri1", "name": "Old"}]
    with open(cache_path, "w") as f:
        json.dump(data, f)
    cache = MappingCache(cache_path)
    assert cache.get_uri("x1") == "uri1"
    assert cache.get_shuffle("x1") is False
```

**Why this matters for tontraeger:** The client-server JSON API is a backward compat boundary. The critical path (NFC → cache → Sonos) must survive any server state. Hard key access in the cache parse path directly violates the "no server dependency on the playback path" invariant.

---

### 2. `CREATE TABLE` Schema Out of Sync with Migrations

**Root cause:** `CREATE TABLE IF NOT EXISTS tags` didn't include `shuffle`. Every fresh database silently swallowed an `OperationalError` from the `ALTER TABLE shuffle` migration.

```python
# Before — shuffle only in ALTER TABLE
cursor.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        tag_uid TEXT PRIMARY KEY,
        media_uri TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT ''
    )
""")

# After — shuffle in DDL (canonical schema) + ALTER TABLE retained for upgrades
cursor.execute("""
    CREATE TABLE IF NOT EXISTS tags (
        tag_uid TEXT PRIMARY KEY,
        media_uri TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        shuffle INTEGER NOT NULL DEFAULT 0
    )
""")
```

Also removed the stale `ALTER TABLE name` block — `name` has been in `CREATE TABLE` since it was added, so the migration was dead weight.

**Rule:** `CREATE TABLE` is the canonical schema definition. `ALTER TABLE` blocks exist only to migrate pre-existing databases. They should agree.

---

### 3. Jinja2 Flash Message Double-Escaping

**Root cause:** `flash(f"... {escape(name or tag_uid)}")` — `escape()` returns a `Markup` object, but embedding it in an f-string converts it back to a plain `str`. Jinja2 then auto-escapes it again: `Rock & Roll` → `Rock &amp;amp; Roll`.

```python
# Before — double-encoded, brittle
from markupsafe import escape
flash(f"Mapping added for tag {escape(name or tag_uid)}")

# After — Jinja2 auto-escaping is the single source of truth
flash(f"Mapping added for tag {name or tag_uid}")
# 'from markupsafe import escape' import removed
```

**Rule:** Flask's `flash()` is rendered by Jinja2 with auto-escaping enabled. Manual `escape()` before passing to `flash()` is always wrong. If you need pre-marked HTML-safe content in a flash message, use `Markup(f"... {escape(var)}")` — but you almost certainly don't need HTML in a flash message.

---

### 4. `run_in_executor` with Positional Arguments

**Root cause:** `run_in_executor(None, self._do_play, uri, shuffle)` passes args positionally. Mypy doesn't check these; a signature change breaks silently at runtime.

```python
# Before — fragile positional args
await loop.run_in_executor(None, self._do_play, uri, shuffle)

# After — lambda makes the call explicit and type-checkable
await loop.run_in_executor(None, lambda: self._do_play(uri, shuffle))
```

**Rule:** When passing a callable to `run_in_executor` with arguments, always use a lambda or `functools.partial`. The positional-args overload of `run_in_executor` is not checked by mypy and breaks invisibly on signature changes.

---

### 5. Testing: Verify at the Right Layer

`FakeSoCo` had no `play_mode` attribute. Tests for `control.py` verified that `DummySonosAPI.played_shuffle` was set, but no test verified that the real `SonosAPI._do_play` actually called `coordinator.play_mode = "SHUFFLE"`. The assignment was untested at the Sonos API layer.

```python
# Added play_mode to FakeSoCo
class FakeSoCo:
    def __init__(self) -> None:
        ...
        self.play_mode: str = ""

# Added tests using real SonosAPI._do_play (not the fake override)
async def test_play_uri_sets_shuffle_mode() -> None:
    fake = FakeSoCo()
    api = SonosAPI("Living Room")
    api._speaker = fake  # type: ignore[assignment]
    await api.play_uri("x-sonosapi-radio:s123", shuffle=True)
    assert fake.play_mode == "SHUFFLE"
```

**Rule:** When a feature adds behavior at multiple layers (controller → API → hardware), there should be at least one test per layer boundary that crosses into the real implementation. A test that stops at a fake interface doesn't verify the translation.

---

### 6. Shuffle Checkbox CSS (UI)

**Root cause:** `.form-field-checkbox` inherited `flex: 1` from `.form-field`, causing it to stretch. `.form-field label` had `display: block`, pushing "SHUFFLE" below the checkbox.

```css
/* Fix */
.form-field-checkbox {
  flex: 0 0 auto;
  align-self: flex-end;
  padding-bottom: 0.6rem;
}

.form-field-checkbox label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
  cursor: pointer;
  margin-bottom: 0;
  white-space: nowrap;
}

.form-field-checkbox input[type="checkbox"] {
  width: 1rem;
  height: 1rem;
  accent-color: var(--amber);
  cursor: pointer;
  flex-shrink: 0;
}
```

**Rule:** Checkbox fields need their own CSS class that overrides the generic `.form-field` flex expansion. `accent-color` is sufficient for theming a native checkbox in modern browsers.

## Prevention

### Code Review Fastchecks

Before merging any feature that adds fields to the JSON API or cache:

1. **Dict key access** — search for `m["key"]` in cache/sync code. Require `.get("key", default)` for any field that could be absent in cached files or older server responses.

2. **Schema sync** — when adding a column via `ALTER TABLE`, also add it to the `CREATE TABLE` DDL. They must agree.

3. **Jinja2 + escape()** — grep for `escape(` in the same expression as `flash()` or a template context variable. It's almost certainly wrong. Trust Jinja2.

4. **`run_in_executor` args** — any call with positional args after the callable should use a lambda instead: `lambda: fn(a, b)`.

5. **Deleted tests** — if a PR removes a test, require an explanation. "The test was failing" is not sufficient. Either fix the code or add a new test covering the same scenario.

6. **Layer coverage** — for features with hardware/network I/O, verify there's at least one test per layer that uses the real implementation (not a full mock) to check the translation between layers.

### API/Cache Backward Compatibility Rule

Any new field added to the `/api/mappings` response must use `.get("field", default)` in `cache._parse()`. This is **mandatory** — it's what keeps the critical path (NFC → cache → Sonos) server-independent after a partial or rolled-back deployment.

## References

- Implementation plan: `docs/plans/2026-03-16-001-feat-shuffle-flag-mappings-plan.md`
- Todos (now complete): `todos/001-complete-p1-cache-parse-shuffle-keyerror.md` through `todos/008-complete-p3-run-in-executor-use-lambda.md`
- Architecture invariant: `CLAUDE.md` — "The critical path has no server dependency"
