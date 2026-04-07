---
title: JavaScript Z-suffix vs Python +00:00 UTC Timestamp Comparison
description: JS Date.toISOString() emits a trailing 'Z'; Python datetime.isoformat() emits '+00:00'. Lexicographic string comparison silently breaks when mixing them.
type: logic-error
date: 2026-03-24
tags: [datetime, javascript, python, iso8601, flask, htmx]
---

## Problem

The tap-to-assign UI polls `GET /api/pending-tags?since=<timestamp>`. The client
sends `since` as `new Date().toISOString()`, which produces:

```
2026-03-24T14:22:07.123Z
```

The server stores `last_seen` via `datetime.now(timezone.utc).isoformat()`, which
produces:

```
2026-03-24T14:22:07.123456+00:00
```

`get_since()` compared them as plain strings:

```python
return [t for t in self._tags.values() if t["last_seen"] >= since_iso]
```

Because `'+' (ASCII 43) < 'Z' (ASCII 90)`, a stored timestamp like
`2026-03-24T14:22:07.123456+00:00` will always compare as *less than* a `since`
value of `2026-03-24T14:22:07.123Z`, even though they represent the same instant.
A tag scanned at the exact moment the user clicks "Assign tag" would never appear.

## Root Cause

Two valid ISO 8601 UTC representations — `Z` and `+00:00` — are not equal as strings.
`Z` sorts lexicographically *after* `+00:00` because `Z > +` in ASCII.

## Fix

Normalize the incoming `since` value before comparison:

```python
# web.py — UnknownTagInbox.get_since()
def get_since(self, since_iso: str) -> list[dict]:
    since_normalized = since_iso.replace("Z", "+00:00")
    return [t for t in self._tags.values() if t["last_seen"] >= since_normalized]
```

This works because Python's `isoformat()` never emits `Z`, so stored values are
always `+00:00`. Normalizing the incoming value makes the comparison consistent.

## Prevention

- Never compare ISO 8601 timestamps as raw strings when mixing Python and JavaScript sources.
- Either parse both into `datetime` objects before comparing, or canonicalize the
  suffix before any string comparison.
- Test with a tag that arrives in the same millisecond window as the polling `since`
  value — that's the edge case where this bug surfaces.

## Test Added

```python
def test_pending_tag_z_suffix_normalized(client) -> None:
    """Tags with last_seen just before a Z-suffix 'since' must still be returned."""
    client.post("/api/unknown-tags", json={"tag_uid": "aabb"})
    last_seen = unknown_tags._tags["aabb"]["last_seen"]
    # JS sends Z suffix; Python stores +00:00 — must match the same instant
    since = last_seen[:23] + "Z"
    rv = client.get(f"/api/pending-tags?since={since}")
    assert rv.status_code == 200
    assert rv.json["tags"] == []
```
