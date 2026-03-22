---
title: "Migrate Alpine.js polling and dropdown to htmx server-rendered fragments"
category: ui-bugs
date: 2026-03-22
tags:
  - htmx
  - alpine-js
  - flask
  - server-side-rendering
  - template-escaping
modules:
  - server/tontraeger_server/web.py
---

# Migrate Alpine.js Polling and Dropdown to htmx Server-Rendered Fragments

## Problem

The unknown tag polling and speaker dropdown were implemented with Alpine.js — client-side JavaScript fetched JSON from API endpoints and rendered HTML dynamically in the browser. This contradicted the project's UI principle of preferring htmx (server-rendered fragments) and created complexity around escaping when interpolating dynamic values into JavaScript expressions inside HTML attributes.

## Root Cause

Alpine.js was originally used because these features involved periodic data fetching (polling) and dynamic UI updates (dropdown population), which felt like client-side concerns. However, htmx's `hx-trigger="every 5s"` and server-rendered fragments handle these patterns cleanly without client-side rendering logic.

## Solution

### 1. Create fragment endpoints that return HTML instead of JSON

```python
def _unknown_tags_html() -> str:
    tags = unknown_tags.get_all()
    if not tags:
        return ""
    cards = []
    for tag in tags:
        uid = escape(tag["tag_uid"])
        count = tag["scan_count"]
        plural = "time" if count == 1 else "times"
        cards.append(
            f'<div class="card">'
            f'<div class="card-tag">{uid}</div>'
            f'<div class="card-uri">Scanned {count} {plural}</div>'
            f'<button data-tag-uid="{uid}"'
            f' @click="$refs.tagUid.value = $el.dataset.tagUid; $refs.tagUid.focus()">Use</button>'
            f'</div>'
        )
    return "".join(cards)

@app.route("/fragments/unknown-tags")
def fragment_unknown_tags() -> Response:
    return Response(_unknown_tags_html(), content_type="text/html")
```

### 2. Replace Alpine.js polling with htmx polling

```html
<!-- Before: Alpine.js JSON fetch + client-side rendering -->
<div x-data="formHelper()" x-init="loadUnknownTags(); setInterval(() => loadUnknownTags(), 5000)">
  <template x-for="tag in unknownTags" :key="tag.tag_uid">...</template>
</div>

<!-- After: htmx server-rendered polling -->
<div hx-get="/fragments/unknown-tags"
     hx-trigger="load, every 5s"
     hx-swap="innerHTML">
</div>
```

### 3. Replace Alpine.js dropdown with htmx load

```html
<!-- Before -->
<select x-model="selectedSpeaker">
  <option value="">Select speaker…</option>
  <template x-for="name in speakers" :key="name">
    <option :value="name" x-text="name"></option>
  </template>
</select>

<!-- After: htmx loads options, Alpine keeps model binding -->
<select x-model="selectedSpeaker"
        hx-get="/fragments/speaker-options"
        hx-trigger="load"
        hx-swap="beforeend">
  <option value="">Select speaker…</option>
</select>
```

### 4. Use data- attributes to avoid dual-context escaping

When server-rendered HTML contains dynamic values inside JS expressions in HTML attributes, separate data from logic:

```python
# BAD: uid inside JS string inside HTML attribute (dual-context escaping)
f'<button @click="$refs.tagUid.value = \'{uid}\'">Use</button>'

# GOOD: data attribute holds the value, JS reads from DOM
f'<button data-tag-uid="{uid}" @click="$refs.tagUid.value = $el.dataset.tagUid">Use</button>'
```

## Decision Heuristic: htmx vs Alpine.js

| Use htmx when | Use Alpine.js when |
|---|---|
| Fetching/mutating server data | Purely client-side DOM manipulation |
| Rendering lists, tables from server | Multi-state UI buttons (loading/error/success) |
| Polling for live updates | UI mode toggles (e.g., print mode) |
| Server already has data + rendering logic | Setting input values, focus management |

**Use both** when a component needs client-side state (Alpine) but also fetches via server (htmx). Alpine directives work on htmx-swapped content as long as the swapped elements land inside an existing `x-data` scope.

## Prevention

- **Never interpolate dynamic values into JS expressions in HTML attributes.** Use `data-` attributes and read via `$el.dataset` or `el.dataset`.
- **Set explicit `content_type="text/html"`** on fragment responses.
- **Fragment endpoints should handle empty state gracefully** — return empty string, not an error.
- **Alpine directives on htmx-swapped content work automatically** if the swap target is inside an `x-data` scope. No special initialization needed.

## Related

- [pure-htmx-inline-edit-without-alpine-state.md](pure-htmx-inline-edit-without-alpine-state.md) — Established pattern for htmx fragment swaps replacing Alpine state
- [htmx-form-fragment-swap-for-image-upload.md](htmx-form-fragment-swap-for-image-upload.md) — Fragment swap pattern for mutations
- [htmx-css-selector-colons-in-ids.md](htmx-css-selector-colons-in-ids.md) — CSS selector gotcha with dynamic IDs
- [hx-boost-bypasses-onsubmit-confirmation.md](hx-boost-bypasses-onsubmit-confirmation.md) — htmx boost interaction with native handlers
