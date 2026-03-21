---
title: "htmx CSS selector fails with colons in element IDs"
category: ui-bugs
date: 2026-03-21
tags: [htmx, css-selectors, nfc, tag-uid, jinja2]
components: [server/tontraeger_server/web.py]
---

## Problem

htmx `hx-target` uses `querySelectorAll` internally. When element IDs contain colons — common with NFC tag UIDs like `04:3d:24:82:e1:71:81` — the selector `#thumb-04:3d:24:82:e1:71:81` is invalid CSS and throws:

```
Uncaught SyntaxError: Failed to execute 'querySelectorAll' on 'Document':
'#thumb-04:3d:24:82:e1:71:81' is not a valid selector.
```

This broke the htmx image upload flow — clicking Save or uploading a file triggered the error and the thumbnail never updated.

## Root Cause

Colons in CSS selectors denote pseudo-classes (`:hover`, `:first-child`). An ID containing literal colons must be escaped (`\:`) to be valid in `querySelectorAll`. htmx passes `hx-target` values directly to `querySelectorAll` without escaping.

## Solution

Add a Jinja2 filter that replaces colons with hyphens, applied to all `id` attributes and `hx-target` selectors. The raw `tag_uid` is preserved in `url_for()` calls and data attributes — only the CSS-facing ID is sanitized.

```python
# Registration (web.py, module level)
app.jinja_env.filters["css_id"] = lambda s: s.replace(":", "-")
```

```html
<!-- Template usage -->
<img id="thumb-{{ tag_uid|css_id }}" ...>

<form hx-post="..." hx-target="#thumb-{{ tag_uid|css_id }}" hx-swap="outerHTML">
```

```python
# Server-side HTML fragment (returned after image upload)
def _thumb_html(tag_uid: str) -> str:
    css_id = escape(tag_uid.replace(":", "-"))
    src = url_for("get_image", tag_uid=tag_uid)
    return f'<img id="thumb-{css_id}" class="card-thumb" src="{src}?v={int(time.time())}" ...>'
```

The `_thumb_html` function must produce the same ID format as the template so htmx can find the target on subsequent swaps.

## Prevention

When using htmx `hx-target` with dynamic IDs, always sanitize the ID value for CSS selector compatibility. Characters that need escaping or replacing: `:`, `.`, `[`, `]`, `>`, `+`, `~`, `#`, spaces. For this project, NFC tag UIDs only contain hex digits and colons, so replacing `:` with `-` is sufficient.

**Test pattern:**

```python
def test_colon_uid_css_safe(client):
    client.post("/mappings", data={"tag_uid": "04:3d:24:82", "media_uri": "uri"})
    resp = client.get("/")
    assert b'id="thumb-04-3d-24-82"' in resp.data
    assert b'hx-target="#thumb-04-3d-24-82"' in resp.data
```
