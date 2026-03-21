---
title: "Use htmx form submissions + fragment swap instead of client-side image replacement"
category: ui-bugs
date: 2026-03-21
tags: [htmx, alpine-js, image-upload, caching, fragment-swap]
components: [server/tontraeger_server/web.py]
---

## Problem

After uploading or changing artwork for a tag mapping, the thumbnail in the UI didn't update. Multiple client-side approaches were tried:

1. **Full page reload** (`location.href = '/?_=' + Date.now()`) — worked but was jarring.
2. **DOM replacement with same URL** — created a new `<img>` element but pointed it at the same `/mappings/{uid}/image` URL. Browser served the cached version. Did not work.
3. **Blob URLs** (`URL.createObjectURL`) via `fetch()` with `cache: 'reload'` — worked, but required ~60 lines of Alpine.js: `FileReader` to base64-encode, `fetch` to POST JSON, second `fetch` to GET the image as a blob, then DOM manipulation to swap the element. Too much client-side dancing for a simple operation.

## Root Cause

The core issue was trying to solve a server-side problem (image changed, UI needs to reflect it) entirely on the client. Each approach added complexity to work around browser caching behavior:
- Same URL = browser cache hit, even with a new DOM element
- Blob URLs bypass cache but require the client to re-fetch and manage object URLs
- Cache-bust query params work but are "trickery" that shouldn't be the primary mechanism

## Solution

Move the logic server-side. The `set_image` endpoint accepts form submissions (not just JSON) and returns an HTML `<img>` fragment. htmx swaps it in with `hx-swap="outerHTML"`.

**Endpoint:** Accept forms in addition to JSON, return HTML for htmx requests:

```python
def _thumb_html(tag_uid: str) -> str:
    css_id = escape(tag_uid.replace(":", "-"))
    src = url_for("get_image", tag_uid=tag_uid)
    return (
        f'<img id="thumb-{css_id}" class="card-thumb"'
        f' src="{src}?v={int(time.time())}"'
        f' alt="artwork" loading="lazy">'
    )

def _wants_html() -> bool:
    return "HX-Request" in request.headers

@app.route("/mappings/<tag_uid>/image", methods=["POST"])
def set_image(tag_uid: str):
    image_data, error, status = _parse_image_payload()
    if error:
        if _wants_html():
            return Response(f"<span>{escape(error)}</span>", status=status)
        return jsonify(error=error), status
    if not mapper.upsert_image(tag_uid, image_data):
        ...
    if _wants_html():
        return Response(_thumb_html(tag_uid))
    return jsonify(ok=True)
```

**Template:** Two htmx forms replace the entire Alpine.js component:

```html
<!-- URL paste -->
<form hx-post="{{ url_for('set_image', tag_uid=tag_uid) }}"
      hx-target="#thumb-{{ tag_uid|css_id }}" hx-swap="outerHTML">
  <input type="text" name="image_url" placeholder="Image URL...">
  <button type="submit">Save</button>
</form>

<!-- File upload -->
<form hx-post="{{ url_for('set_image', tag_uid=tag_uid) }}"
      hx-target="#thumb-{{ tag_uid|css_id }}" hx-swap="outerHTML"
      hx-encoding="multipart/form-data">
  <input type="file" name="image_file" accept="image/*"
         onchange="this.form.requestSubmit()">
</form>
```

The `?v={timestamp}` on the returned `<img>` src ensures the browser fetches the new image rather than serving a stale cached version. The returned fragment carries the same `id` as the element it replaces, so subsequent uploads keep working.

**Result:** ~60 lines of Alpine.js (FileReader, fetch, blob URLs, DOM manipulation) replaced by two declarative htmx forms and a 7-line Python helper. The JSON API path is preserved for the client component.

## Prevention

When updating a server-rendered element after a mutation, prefer returning a new HTML fragment from the mutation endpoint over client-side DOM manipulation. This is the htmx pattern: POST to mutate, receive the updated fragment, swap it in. It avoids browser cache issues entirely because the server controls the `src` URL with a fresh cache-bust parameter.

**Decision heuristic:** If you find yourself writing `fetch()` + DOM manipulation in Alpine/JS to update something after a POST, consider whether the endpoint can just return the new HTML instead.
