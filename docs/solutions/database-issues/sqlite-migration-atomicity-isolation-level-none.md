---
title: SQLite Schema Migration Atomicity with isolation_level=None
description: Python's sqlite3 default isolation mode auto-commits DDL statements, making multi-step table-recreation migrations non-atomic. Use isolation_level=None + explicit BEGIN IMMEDIATE.
type: database-issue
date: 2026-03-24
tags: [sqlite, migration, atomicity, python, flask]
---

## Problem

The schema migration in `TagMapper._init_db()` recreates a table using the
standard SQLite pattern:

1. `CREATE TABLE tags_new (...)`
2. `INSERT INTO tags_new SELECT ... FROM tags`
3. `DROP TABLE tags`
4. `ALTER TABLE tags_new RENAME TO tags`

With Python's default `sqlite3.connect(path)` (i.e. `isolation_level=""` which
uses deferred transactions), **DDL statements like `DROP TABLE` and `ALTER TABLE`
are auto-committed**. This means steps 3 and 4 run in separate implicit
transactions. A crash between them leaves the database in an unrecoverable state:
`tags` is gone, but `tags_new` exists with all the data and no index.

Additionally, `ALTER TABLE tags ADD COLUMN` was being attempted before checking
whether the table even existed (fresh databases). The `except OperationalError`
catch was silently eating "no such table" errors alongside the intended "column
already exists" errors.

## Fix

### 1. Switch to autocommit mode for the entire `_init_db` call

```python
conn = sqlite3.connect(self.db_path, isolation_level=None)  # autocommit mode
```

With `isolation_level=None`, no implicit transactions are opened. You control
transactions entirely via explicit SQL.

### 2. Guard ALTER TABLE behind a table-existence check

```python
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tags'")
if cursor.fetchone():
    try:
        cursor.execute("ALTER TABLE tags ADD COLUMN shuffle INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
```

Only attempt `ALTER TABLE` when the table is confirmed to exist.

### 3. Wrap the 4-step recreation in an explicit transaction

```python
cursor.execute("BEGIN IMMEDIATE")
cursor.execute("DROP TABLE IF EXISTS tags_new")  # cleanup from prior partial run
cursor.execute("CREATE TABLE tags_new (...)")
cursor.execute("INSERT INTO tags_new SELECT ... FROM tags ORDER BY tag_uid")
cursor.execute("DROP TABLE tags")
cursor.execute("ALTER TABLE tags_new RENAME TO tags")
cursor.execute("COMMIT")
```

`BEGIN IMMEDIATE` acquires a write lock upfront. All four DDL steps are now
atomic — a crash at any point causes SQLite to roll back, and `_init_db` will
re-run cleanly on the next startup (the `DROP TABLE IF EXISTS tags_new` guard
handles any leftover `tags_new` from a prior partial run).

## Prevention

- Always use `isolation_level=None` + explicit `BEGIN/COMMIT` for any migration
  that involves multiple DDL steps.
- Include a `DROP TABLE IF EXISTS <temp_table>` at the start of the migration
  block to make it idempotent.
- Guard `ALTER TABLE ADD COLUMN` with a table-existence check when the code runs
  on both fresh and existing databases.
- Relevant SQLite docs: DDL statements are transactional in SQLite (unlike most
  other databases), but only if you explicitly open a transaction.
