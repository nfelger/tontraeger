---
title: "refactor: Migrate unknown tag polling and speaker dropdown from Alpine.js to htmx"
type: refactor
status: completed
date: 2026-03-22
origin: docs/brainstorms/2026-03-22-alpine-htmx-migration-brainstorm.md
---

# Migrate Unknown Tag Polling and Speaker Dropdown to htmx

## Overview

Replace two Alpine.js features with htmx server-rendered patterns: unknown tag polling/rendering and speaker dropdown population. Also update CLAUDE.md to clarify the htmx/Alpine.js boundary. (See brainstorm: docs/brainstorms/2026-03-22-alpine-htmx-migration-brainstorm.md)

## Acceptance Criteria

- [x] Unknown tags section polls via `hx-trigger="every 5s"` and renders server-returned HTML fragments
- [x] Speaker dropdown populates via `hx-get` on page load with server-returned `<option>` elements
- [x] "Use" button still works (kept as Alpine.js — copies tag UID into form input)
- [x] Speaker auto-select still works when only one speaker exists (kept as Alpine.js)
- [x] Now Playing button still works (kept as Alpine.js)
- [x] Print mode still works (kept as Alpine.js)
- [x] Alpine.js `formHelper` component is simplified — `loadSpeakers()` and `loadUnknownTags()` removed
- [x] CLAUDE.md UI Principles updated to clarify htmx-first-but-not-htmx-only stance
- [x] `make check` passes
- [x] Tests cover the new HTML fragment endpoints

## MVP

### Step 1: New endpoint — unknown tags HTML fragment

Add a route that returns the unknown tags section as an HTML fragment.

#### `web.py` — new helper function `_unknown_tags_html()`

```python
def _unknown_tags_html() -> str:
    tags = unknown_tags.get_all()
    if not tags:
        return ""
    cards = []
    for tag in tags:
        uid = tag["tag_uid"]
        count = tag["scan_count"]
        plural = "time" if count == 1 else "times"
        cards.append(f"""
        <div class="card">
          <div class="card-groove"></div>
          <div class="card-body">
            <div class="card-tag">{uid}</div>
            <div class="card-uri">Scanned {count} {plural}</div>
          </div>
          <div class="card-actions">
            <button type="button" class="btn btn-now-playing"
                    @click="$refs.tagUid.value = '{uid}'; $refs.tagUid.focus()">Use</button>
          </div>
        </div>""")
    badge = len(tags)
    return f"""
    <div class="section-head">
      <h2>Recently Scanned</h2>
      <span class="badge">{badge}</span>
    </div>
    {''.join(cards)}"""
```

#### `web.py` — new route

```python
@app.route("/fragments/unknown-tags")
def fragment_unknown_tags() -> Response:
    return Response(_unknown_tags_html())
```

### Step 2: New endpoint — speaker options HTML fragment

```python
def _speaker_options_html() -> str:
    try:
        speakers = soco.discover(timeout=5)
        if not speakers:
            return ""
        names = sorted(s.player_name for s in speakers)
        options = []
        for name in names:
            selected = " selected" if len(names) == 1 else ""
            options.append(f'<option value="{name}"{selected}>{name}</option>')
        return "\n".join(options)
    except Exception:
        return ""

@app.route("/fragments/speaker-options")
def fragment_speaker_options() -> Response:
    return Response(_speaker_options_html())
```

Note: auto-select when only one speaker is handled server-side via the `selected` attribute. The Alpine store `speaker.selected` still needs to be synced — a small Alpine `@change` or `x-init` on the `<select>` can read the selected value after htmx swaps in the options.

### Step 3: Update the template — unknown tags section

Replace the Alpine.js `x-for` / `x-show` unknown tags block with an htmx-polled container:

```html
<div id="unknown-tags-container"
     hx-get="/fragments/unknown-tags"
     hx-trigger="load, every 5s"
     hx-swap="innerHTML"
     class="unknown-tags">
</div>
```

Remove: `x-show="unknownTags.length > 0"`, `x-cloak`, `x-for="tag in unknownTags"`, `x-text` directives, and the `@click="useTag(tag.tag_uid)"` handler (replaced by inline `@click` in the server-rendered fragment that uses `$refs`).

### Step 4: Update the template — speaker dropdown

Replace the Alpine.js `x-for` speaker options with htmx-loaded options:

```html
<select id="speaker" x-model="selectedSpeaker"
        hx-get="/fragments/speaker-options"
        hx-trigger="load"
        hx-swap="beforeend">
  <option value="">Select speaker&hellip;</option>
</select>
```

The `x-model="selectedSpeaker"` stays — Alpine.js still manages the speaker store for the Now Playing button. When htmx swaps in the `<option>` elements (including a pre-selected one if only one speaker), Alpine picks up the change via the `x-model` binding.

### Step 5: Simplify `formHelper` Alpine component

Remove from `formHelper`:
- `speakers: []`
- `loadSpeakers()` method
- `unknownTags: []`
- `loadUnknownTags()` method
- `useTag()` method (moved to inline `@click` in server-rendered fragment)

Remove from `x-init`:
- `loadSpeakers()`
- `loadUnknownTags()`
- `setInterval(() => loadUnknownTags(), 5000)`

What remains in `formHelper`:
- `selectedSpeaker` (getter/setter for speaker store)
- `npLoading`, `npButtonText`
- `fetchNowPlaying()`

### Step 6: Update CLAUDE.md

Update the UI Principles section:

```markdown
## UI Principles

- **Prefer htmx for server-driven interactions** (data fetching, rendering lists, polling, state transitions). Use htmx server-rendered HTML fragments + swaps as the default for all UI interactions.
- **Use Alpine.js where it's genuinely simpler** than htmx — e.g., client-side DOM manipulation (setting input values), UI mode toggles, multi-state buttons, or reactive state that doesn't need a server round-trip. Alpine.js is a complement to htmx, not a last resort.
```

### Step 7: Tests

Add tests for the new fragment endpoints:

#### `test_web.py`

```python
def test_fragment_unknown_tags_empty(client):
    resp = client.get("/fragments/unknown-tags")
    assert resp.status_code == 200
    assert resp.data == b""

def test_fragment_unknown_tags_with_tags(client):
    client.post("/api/unknown-tags", json={"tag_uid": "AA:BB:CC"})
    resp = client.get("/fragments/unknown-tags")
    assert resp.status_code == 200
    assert b"AA:BB:CC" in resp.data
    assert b"Scanned 1 time" in resp.data
    assert b"Use" in resp.data

def test_fragment_speaker_options(client, mock_soco):
    resp = client.get("/fragments/speaker-options")
    assert resp.status_code == 200
    # Content depends on mock_soco setup
```

## Technical Considerations

- **"Use" button `@click` in server-rendered HTML**: The `@click="$refs.tagUid.value = '...'"` in the server fragment works because the unknown tags container is inside the `x-data="formHelper()"` scope. Alpine.js `$refs` are available to any element within the `x-data` scope, even if dynamically inserted by htmx.
- **htmx + Alpine.js coexistence**: htmx processes new elements after swap. Alpine.js also needs to initialize on new elements — htmx dispatches `htmx:afterSwap` events which Alpine handles automatically when both libraries are loaded. No special configuration needed.
- **CSS selector gotcha**: The unknown tags container uses a simple `id="unknown-tags-container"` without colons, so the documented CSS selector issue doesn't apply here.
- **Speaker store sync**: After htmx loads the `<option>` elements into the `<select>`, Alpine.js's `x-model` binding may need a manual dispatch of a `change` event to sync the store. Test this — if the pre-selected option doesn't sync, add `hx-on::after-swap="this.dispatchEvent(new Event('input'))"` to the `<select>`.

## Sources

- **Origin brainstorm:** [docs/brainstorms/2026-03-22-alpine-htmx-migration-brainstorm.md](docs/brainstorms/2026-03-22-alpine-htmx-migration-brainstorm.md) — key decisions: htmx-first not htmx-only; migrate polling + speakers; keep Use button, Now Playing, print mode as Alpine.js
- **Existing htmx patterns:** `web.py` inline edit endpoints (`/mappings/<tag_uid>/edit-form`, `/mappings/<tag_uid>/card`)
- **Institutional learning:** `docs/solutions/ui-bugs/pure-htmx-inline-edit-without-alpine-state.md` — decision heuristic for htmx vs Alpine.js
- **Institutional learning:** `docs/solutions/ui-bugs/htmx-css-selector-colons-in-ids.md` — CSS selector gotcha (not directly applicable but good to remember)
