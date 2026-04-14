import base64
import hashlib
import json
import secrets
import sqlite3
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from flask import Flask, flash, jsonify, redirect, render_template_string, request, url_for
from markupsafe import escape
from werkzeug.wrappers import Response

import soco

from tontraeger_server.config import DATABASE_PATH
from tontraeger_server.sonos_api import SonosAPI
from tontraeger_server.tag_mapper import TagMapper


class UnknownTagInbox:
    """In-memory store for unknown tag scans. Max 20 entries, FIFO eviction."""

    MAX_SIZE = 20

    def __init__(self) -> None:
        self._tags: OrderedDict[str, dict] = OrderedDict()

    def report(self, tag_uid: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if tag_uid in self._tags:
            entry = self._tags[tag_uid]
            entry["last_seen"] = now
            entry["scan_count"] += 1
            self._tags.move_to_end(tag_uid)
        else:
            if len(self._tags) >= self.MAX_SIZE:
                self._tags.popitem(last=False)
            self._tags[tag_uid] = {
                "tag_uid": tag_uid,
                "first_seen": now,
                "last_seen": now,
                "scan_count": 1,
            }

    def get_all(self) -> list[dict]:
        return list(self._tags.values())

    def get_since(self, since_iso: str) -> dict | None:
        """Return the most recently seen unknown tag after since_iso, or None."""
        # Normalize Z suffix to +00:00 so string comparison works correctly.
        # JS sends "2026-03-24T10:30:00.123Z" but server timestamps use "+00:00".
        # Without normalization, "123456+00:00" < "123Z" ('+' < 'Z'), causing
        # false negatives for tags scanned within the same millisecond as since.
        since_normalized = since_iso.replace("Z", "+00:00")
        for entry in reversed(list(self._tags.values())):
            if entry["last_seen"] > since_normalized:
                return entry
        return None

    def clear(self) -> None:
        self._tags.clear()


app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
app.jinja_env.filters["css_id"] = lambda s: s.replace(":", "-")

mapper = TagMapper(DATABASE_PATH)
unknown_tags = UnknownTagInbox()

MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


def fetch_image_as_base64(url: str) -> str | None:
    """Fetches an image from a URL and returns it as a base64-encoded string."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    try:
        req = Request(url, headers={"User-Agent": "tontraeger/1.0"})
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            data = resp.read(MAX_IMAGE_SIZE + 1)
            if len(data) > MAX_IMAGE_SIZE:
                return None
            return base64.b64encode(data).decode("ascii")
    except (URLError, OSError, ValueError):
        return None


def fetch_spotify_oembed(spotify_url: str) -> dict[str, Any] | None:
    """Fetches oEmbed metadata for a Spotify URL (title, thumbnail, etc.)."""
    oembed_url = f"https://open.spotify.com/oembed?url={quote(spotify_url, safe='')}"
    try:
        req = Request(oembed_url, headers={"User-Agent": "tontraeger/1.0"})
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            return json.loads(resp.read(16384))
    except (URLError, OSError, ValueError, KeyError):
        return None


def fetch_spotify_artwork(spotify_url: str) -> str | None:
    """Fetches artwork for a Spotify URL via the public oEmbed endpoint."""
    data = fetch_spotify_oembed(spotify_url)
    if data:
        thumbnail_url = data.get("thumbnail_url")
        if thumbnail_url:
            return fetch_image_as_base64(thumbnail_url)
    return None


def detect_image_content_type(data: bytes) -> str:
    """Detects image content type from magic bytes."""
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tontraeger</title>
<script src="https://unpkg.com/htmx.org@2.0.4"></script>
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.9/dist/cdn.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

  * { margin: 0; padding: 0; box-sizing: border-box; }

  :root {
    --bg:       #0f0e0c;
    --surface:  #1c1917;
    --border:   #2e2a25;
    --cream:    #f5f0e8;
    --muted:    #a8a08e;
    --amber:    #d4731a;
    --amber-hi: #ef8c2e;
    --red:      #c0392b;
    --red-hi:   #e74c3c;
    --green:    #6a9f5c;
  }

  body {
    background: var(--bg);
    color: var(--cream);
    font-family: 'Inter', system-ui, sans-serif;
    min-height: 100vh;
    line-height: 1.5;
  }

  .container {
    max-width: 680px;
    margin: 0 auto;
    padding: 2rem 1.25rem 4rem;
  }

  /* ── Header ──────────────────────────────── */
  header {
    text-align: center;
    margin-bottom: 2.5rem;
    padding-bottom: 2rem;
    border-bottom: 1px solid var(--border);
  }

  header h1 {
    font-family: 'DM Serif Display', Georgia, serif;
    font-size: 2.8rem;
    font-weight: 400;
    letter-spacing: -0.02em;
    color: var(--cream);
    margin-bottom: 0.15rem;
  }

  header h1 span {
    color: var(--amber);
  }

  header .subtitle {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.25em;
    color: var(--muted);
  }

  /* ── Flash messages ──────────────────────── */
  .flash {
    padding: 0.65rem 1rem;
    border-radius: 6px;
    margin-bottom: 1.5rem;
    font-size: 0.85rem;
    background: #1a2e1a;
    border: 1px solid #2d4a2d;
    color: var(--green);
  }

  /* ── Add form ────────────────────────────── */
  .add-form {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.5rem;
    margin-bottom: 2.5rem;
  }

  .add-form h2 {
    font-family: 'DM Serif Display', Georgia, serif;
    font-size: 1.15rem;
    font-weight: 400;
    margin-bottom: 1rem;
    color: var(--amber);
  }

  .form-row {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .form-field {
    flex: 1;
    min-width: 0;
  }

  .form-field label {
    display: block;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: var(--muted);
    margin-bottom: 0.3rem;
  }

  .form-field input, .form-field select {
    width: 100%;
    padding: 0.6rem 0.75rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--cream);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    transition: border-color 0.2s;
  }

  .form-field input:focus, .form-field select:focus {
    outline: none;
    border-color: var(--amber);
  }

  .form-field input::placeholder {
    color: #4a4540;
  }

  .form-field select {
    appearance: none;
    cursor: pointer;
  }

  .btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.6rem 1.3rem;
    border: none;
    border-radius: 6px;
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    cursor: pointer;
    transition: background 0.2s, transform 0.1s;
    text-decoration: none;
  }

  .btn:active { transform: scale(0.97); }

  .btn-primary {
    background: var(--amber);
    color: #000;
    align-self: flex-end;
    margin-top: 0.3rem;
  }
  .btn-primary:hover { background: var(--amber-hi); }

  .btn-now-playing {
    background: transparent;
    color: var(--amber);
    border: 1px solid var(--amber);
    white-space: nowrap;
  }
  .btn-now-playing:hover {
    background: rgba(212, 115, 26, 0.12);
    color: var(--amber-hi);
    border-color: var(--amber-hi);
  }
  .btn-now-playing.loading {
    opacity: 0.6;
    pointer-events: none;
  }
  .btn-now-playing:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .btn-delete {
    background: transparent;
    color: var(--muted);
    padding: 0.35rem 0.65rem;
    font-size: 0.75rem;
    border: 1px solid var(--border);
  }
  .btn-delete:hover {
    color: var(--red-hi);
    border-color: var(--red);
    background: rgba(192, 57, 43, 0.1);
  }

  /* ── Section headings ────────────────────── */
  .section-head {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    margin-bottom: 1rem;
  }

  .section-head h2 {
    font-family: 'DM Serif Display', Georgia, serif;
    font-size: 1.3rem;
    font-weight: 400;
  }

  .badge {
    font-size: 0.7rem;
    font-weight: 600;
    padding: 0.15rem 0.55rem;
    border-radius: 99px;
    background: var(--amber);
    color: #000;
  }

  .badge-shuffle {
    font-size: 0.75rem;
    opacity: 0.6;
  }

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

  .empty {
    text-align: center;
    color: var(--muted);
    padding: 3rem 1rem;
    font-style: italic;
    border: 1px dashed var(--border);
    border-radius: 10px;
  }

  /* ── Cards (mappings + unknown tags) ─────── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1rem 1.25rem;
    margin-bottom: 0.6rem;
    display: flex;
    align-items: center;
    gap: 1rem;
    transition: border-color 0.2s;
  }

  .card:hover {
    border-color: #3e3830;
  }

  .card-groove {
    width: 42px;
    height: 42px;
    border-radius: 50%;
    background: radial-gradient(circle at center, #333 18%, transparent 19%),
                repeating-radial-gradient(circle at center, transparent, transparent 3px, #222 3.5px, transparent 4px);
    background-color: #1a1a1a;
    border: 2px solid #2a2520;
    flex-shrink: 0;
  }

  .card-body {
    flex: 1;
    min-width: 0;
    overflow: hidden;
  }

  .card-tag {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--cream);
  }

  .card-uri {
    font-size: 0.78rem;
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    margin-top: 0.1rem;
  }

  .card-uri.stop-cmd {
    color: var(--amber);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .card-actions {
    flex-shrink: 0;
  }

  /* ── Unknown tags ────────────────────────── */
  .unknown-tags {
    margin-bottom: 2.5rem;
  }


  /* ── Footer ──────────────────────────────── */
  footer {
    text-align: center;
    margin-top: 3rem;
    padding-top: 1.5rem;
    border-top: 1px solid var(--border);
    font-size: 0.7rem;
    color: #3e3830;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  /* ── Print selection mode ───────────────── */
  .print-checkbox {
    flex-shrink: 0;
  }

  .print-checkbox input[type="checkbox"] {
    width: 1.1rem;
    height: 1.1rem;
    accent-color: var(--amber);
    cursor: pointer;
  }

  .print-checkbox input[type="checkbox"]:disabled {
    opacity: 0.3;
    cursor: not-allowed;
  }

  /* ── Artwork thumbnail + capture ─────────── */
  .card-thumb {
    width: 42px;
    height: 42px;
    border-radius: 6px;
    object-fit: cover;
    flex-shrink: 0;
  }

  .card-thumb-placeholder {
    width: 42px;
    height: 42px;
    border-radius: 6px;
    background: var(--bg);
    border: 1px dashed var(--border);
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--muted);
    font-size: 1rem;
  }

  .artwork-controls {
    display: flex;
    gap: 0.4rem;
    align-items: center;
    flex-shrink: 0;
  }

  .artwork-controls .form-field-url {
    flex: 0 0 auto;
  }

  .artwork-controls .form-field-url input {
    width: 160px;
    padding: 0.35rem 0.5rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--cream);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
  }

  .artwork-controls .form-field-url input::placeholder {
    color: #4a4540;
  }

  .artwork-controls .form-field-url input:focus {
    outline: none;
    border-color: var(--amber);
  }

  .btn-save-url {
    background: transparent;
    color: var(--amber);
    border: 1px solid var(--border);
    padding: 0.3rem 0.5rem;
    font-size: 0.7rem;
  }
  .btn-save-url:hover {
    border-color: var(--amber);
  }

  /* ── Edit mode ─────────────────────────────── */
  .btn-edit {
    background: transparent;
    color: var(--muted);
    padding: 0.35rem 0.65rem;
    font-size: 0.75rem;
    border: 1px solid var(--border);
  }
  .btn-edit:hover {
    color: var(--amber);
    border-color: var(--amber);
  }

  .card-editing {
    border-color: var(--amber);
    flex-wrap: wrap;
  }

  .card-editing .card-body {
    flex: 1 1 100%;
    order: 2;
  }

  .card-editing .card-thumb,
  .card-editing .card-thumb-placeholder {
    order: 1;
  }

  .card-edit-footer {
    order: 3;
    flex: 1 1 100%;
    display: flex;
    align-items: center;
    padding-top: 0.6rem;
    border-top: 1px solid var(--border);
  }

  .card-actions-edit {
    display: flex;
    gap: 0.4rem;
    align-items: center;
  }

  .btn-sm {
    padding: 0.35rem 0.8rem;
    font-size: 0.75rem;
    margin-top: 0;
  }

  .edit-fields {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-bottom: 0.6rem;
  }

  .edit-fields .form-field input {
    width: 100%;
    padding: 0.5rem 0.65rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--cream);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
  }

  .edit-fields .form-field input:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .edit-fields .form-field input:focus {
    outline: none;
    border-color: var(--amber);
  }

  .edit-fields .form-field input::placeholder {
    color: #4a4540;
  }

  .edit-image-controls {
    margin-bottom: 0.6rem;
  }

  .edit-image-controls > label {
    display: block;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: var(--muted);
    margin-bottom: 0.3rem;
  }

  .edit-image-row {
    display: flex;
    gap: 0.4rem;
    align-items: center;
  }

  .edit-checkbox-wrap {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.65rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    cursor: pointer;
  }

  .edit-checkbox-wrap input[type="checkbox"] {
    width: 1rem;
    height: 1rem;
    accent-color: var(--amber);
    cursor: pointer;
    margin: 0;
  }

  .edit-checkbox-wrap label {
    font-size: 0.82rem;
    color: var(--cream);
    cursor: pointer;
    text-transform: none;
    letter-spacing: 0;
    margin: 0;
  }

  .edit-image-url-form {
    flex: 1;
    display: flex;
    gap: 0.4rem;
    align-items: center;
  }

  .edit-image-url-form input {
    flex: 1;
    padding: 0.35rem 0.5rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--cream);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
  }

  .edit-image-url-form input::placeholder {
    color: #4a4540;
  }

  .edit-image-url-form input:focus {
    outline: none;
    border-color: var(--amber);
  }

  .edit-error {
    background: rgba(192, 57, 43, 0.15);
    border: 1px solid var(--red);
    color: var(--red-hi);
    padding: 0.4rem 0.7rem;
    border-radius: 6px;
    font-size: 0.8rem;
    margin-bottom: 0.5rem;
  }

  /* ── Responsive ──────────────────────────── */
  @media (max-width: 500px) {
    header h1 { font-size: 2rem; }
    .form-row { flex-direction: column; }
    .btn-primary { width: 100%; }
    .card { flex-wrap: wrap; gap: 0.6rem; }
    .card-groove { display: none; }
    .artwork-controls { flex-wrap: wrap; }
    .artwork-controls .form-field-url input { width: 120px; }
    .card-actions-edit { flex-wrap: wrap; }
  }
</style>
</head>
<body hx-boost="true">
<div class="container">

  <header>
    <h1>tontraeger</h1>
    <div class="subtitle">Tag &amp; Groove Manager</div>
  </header>

  {% with messages = get_flashed_messages() %}
    {% for msg in messages %}
      <div class="flash">{{ msg }}</div>
    {% endfor %}
  {% endwith %}

  <div x-data="formHelper()">

    <div class="add-form">
      <h2>New Mapping</h2>
      <form method="post" action="{{ url_for('add_mapping') }}">
        <div class="form-row">
          <div class="form-field">
            <label for="name">Name</label>
            <input type="text" id="name" name="name" x-ref="name" @input="nameAutoFilled = false" placeholder="e.g. Kids playlist">
          </div>
          <div class="form-field">
            <label for="tag_uid">Tag UID</label>
            <input type="text" id="tag_uid" name="tag_uid" x-ref="tagUid" placeholder="e.g. 123456789">
          </div>
          <div class="form-field">
            <label for="media_uri">Media URI</label>
            <input type="text" id="media_uri" name="media_uri" x-ref="mediaUri" @input="debouncedFetchMetadata()" placeholder="Spotify link, Sonos URI, or STOP" required>
          </div>
          <div class="form-field form-field-checkbox">
            <label><input type="checkbox" name="shuffle"> Shuffle</label>
          </div>
          <button type="submit" class="btn btn-primary">Add</button>
        </div>
      </form>
      <div style="display:flex; align-items:flex-end; gap:0.5rem; margin-top:0.75rem;">
        <div class="form-field" style="flex:0 1 auto; min-width:140px;">
          <label for="speaker">Speaker</label>
          <select id="speaker" x-model="selectedSpeaker"
                  hx-get="/fragments/speaker-options"
                  hx-trigger="load"
                  hx-swap="beforeend">
            <option value="">Select speaker&hellip;</option>
          </select>
        </div>
        <button type="button" class="btn btn-now-playing"
                @click="fetchNowPlaying()"
                :class="{ loading: npLoading }"
                :disabled="npLoading || !selectedSpeaker"
                x-text="npButtonText">
          Now Playing
        </button>
      </div>
    </div>

    <div id="unknown-tags-container"
         hx-get="/fragments/unknown-tags"
         hx-trigger="load, every 5s"
         hx-swap="innerHTML"
         class="unknown-tags">
    </div>

  </div>

  <div>
  <div class="section-head">
    <h2>Mappings</h2>
    <span class="badge">{{ mappings|length }}</span>
    <div style="margin-left:auto; display:flex; gap:0.4rem;">
      <button x-data x-show="!$store.printMode.active" type="button" class="btn btn-save-url"
              @click="$store.printMode.active = true">Print tags</button>
      <template x-data x-if="$store.printMode.active">
        <div style="display:flex; gap:0.4rem;">
          <button type="button" class="btn btn-primary" style="margin-top:0; font-size:0.75rem; padding:0.35rem 0.8rem;"
                  :disabled="$store.printMode.selected.size === 0"
                  @click="window.open('/print?' + Array.from($store.printMode.selected).map(i => 'id=' + i).join('&'), '_blank')">
            Print selected (<span x-text="$store.printMode.selected.size"></span>)
          </button>
          <button type="button" class="btn btn-delete"
                  @click="$store.printMode.active = false; $store.printMode.selected = new Set()">Cancel</button>
        </div>
      </template>
    </div>
  </div>

  {% if card_htmls %}
    {% for card_html in card_htmls %}
      {{ card_html|safe }}
    {% endfor %}
  {% else %}
    <div class="empty">No mappings yet &mdash; scan a tag and add it above.</div>
  {% endif %}
  </div>

  <footer>tontraeger &middot; Vinyl In, Sound Out</footer>

</div>
<script>
document.addEventListener('alpine:init', () => {
    Alpine.store('speaker', { selected: '' });
    Alpine.store('printMode', { active: false, selected: new Set() });

    Alpine.data('formHelper', () => ({
        get selectedSpeaker() { return Alpine.store('speaker').selected; },
        set selectedSpeaker(v) { Alpine.store('speaker').selected = v; },
        npLoading: false,
        npButtonText: 'Now Playing',
        nameAutoFilled: false,
        _metadataTimer: null,

        debouncedFetchMetadata() {
            clearTimeout(this._metadataTimer);
            this._metadataTimer = setTimeout(() => {
                this.fetchMetadata(this.$refs.mediaUri.value);
            }, 400);
        },

        async fetchMetadata(url) {
            if (!url) return;
            if (this.$refs.name.value && !this.nameAutoFilled) return;
            try {
                const resp = await fetch('/api/media-metadata', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({url: url})
                });
                const data = await resp.json();
                if (data.title && (!this.$refs.name.value || this.nameAutoFilled)) {
                    this.$refs.name.value = data.title;
                    this.nameAutoFilled = true;
                }
            } catch (e) {
                // silently ignore — name field stays as-is
            }
        },

        async fetchNowPlaying() {
            if (!this.selectedSpeaker) return;
            this.npLoading = true;
            this.npButtonText = 'Fetching\u2026';
            try {
                const resp = await fetch('/now-playing?speaker=' + encodeURIComponent(this.selectedSpeaker));
                const data = await resp.json();
                if (data.uri) {
                    this.$refs.mediaUri.value = data.uri;
                    this.$refs.mediaUri.focus();
                    this.fetchMetadata(data.uri);
                    this.npButtonText = 'Now Playing';
                } else {
                    this.npButtonText = 'Nothing playing';
                    setTimeout(() => { this.npButtonText = 'Now Playing'; }, 2000);
                }
            } catch (e) {
                this.npButtonText = 'Error';
                setTimeout(() => { this.npButtonText = 'Now Playing'; }, 2000);
            } finally {
                this.npLoading = false;
            }
        }
    }));

});
</script>
</body>
</html>
"""


PRINT_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Print Tags</title>
<style>
  /* Print layout for two-cut lamination workflow:
     1. Straight cuts to separate cards (rows/columns in one motion)
     2. Place in lamination pouch, laminate, cut ~3mm outside card

     Printed cards: 59×59mm. After laminating with 3mm seal = 65×65mm.
     Grid: 3 cols × 4 rows of 59mm cells on A4 (210×297mm).
     3×59 = 177mm wide — fits within typical ~5mm unprintable margins.
     4×59 = 236mm tall, centered vertically. */

  @page {
    size: A4;
    margin: 0;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    width: 210mm;
    margin: 0 auto;
    background: #fff;
    font-family: sans-serif;
  }

  .sheet {
    width: 210mm;
    min-height: 297mm;
    position: relative;
    page-break-after: always;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(3, 59mm);
    grid-auto-rows: 59mm;
    justify-content: center;
    padding-top: 8mm;
  }

  .cell {
    width: 59mm;
    height: 59mm;
    position: relative;
  }

  /* Artwork fills the 59mm card, clipped to rounded corners */
  .cell img {
    position: absolute;
    top: 0;
    left: 0;
    width: 59mm;
    height: 59mm;
    object-fit: contain;
    border-radius: 3mm;
    display: block;
  }

  /* Rounded cut outline — overlays on top of artwork so it's
     visible even on white-background images */
  .card-outline {
    position: absolute;
    top: 0;
    left: 0;
    width: 59mm;
    height: 59mm;
    border: 0.3mm solid #aaa;
    border-radius: 3mm;
    z-index: 1;
  }

  /* Cutting guides — lines from page edge to grid boundary for
     trimmer alignment. Extend to the edge so at least 5mm remains
     visible after the printer clips its unprintable margin. */
  .cut-guide {
    position: absolute;
    background: #aaa;
  }

  .instructions {
    text-align: center;
    padding: 1rem;
    color: #999;
    font-size: 0.8rem;
  }

  @media print {
    .instructions { display: none; }
    body { width: auto; margin: 0; }
  }

  @media screen {
    body { padding: 1rem; background: #f0f0f0; }
    .sheet { background: #fff; box-shadow: 0 2px 10px rgba(0,0,0,0.15); margin-bottom: 1rem; }
  }
</style>
</head>
<body>
  <div class="instructions">
    Set print scale to <strong>100%</strong> and paper to <strong>A4</strong>.<br>
    Cut along the rounded outline (59&times;59mm), then laminate and trim with 3mm sealed border for 65&times;65mm cards.
  </div>
  {% for page_cards in pages %}
  <div class="sheet">
    <div class="grid">
      {% for mid in page_cards %}
      <div class="cell">
        <img src="{{ url_for('get_image', mapping_id=mid) }}" alt="artwork">
        <div class="card-outline"></div>
      </div>
      {% endfor %}
    </div>
    {% if page_cards %}
    {% set n_rows = ((page_cards | length - 1) // 3 + 1) %}
    {% for col in range(4) %}
    <div class="cut-guide" style="left:{{ 16.5 + col * 59 }}mm; top:0; width:0.3mm; height:8mm;"></div>
    <div class="cut-guide" style="left:{{ 16.5 + col * 59 }}mm; top:{{ 8 + n_rows * 59 }}mm; width:0.3mm; bottom:0;"></div>
    {% endfor %}
    {% for row in range(n_rows + 1) %}
    <div class="cut-guide" style="top:{{ 8 + row * 59 }}mm; left:0; height:0.3mm; width:16.5mm;"></div>
    <div class="cut-guide" style="top:{{ 8 + row * 59 }}mm; right:0; height:0.3mm; width:16.5mm;"></div>
    {% endfor %}
    {% endif %}
  </div>
  {% endfor %}
</body>
</html>
"""


CARDS_PER_PAGE = 12  # 3 columns × 4 rows on A4


@app.route("/print")
def print_tags() -> str:
    ids = request.args.getlist("id", type=int)
    rows = mapper.get_mappings_with_images(ids)
    valid_ids = [mid for mid, _data in rows]
    pages = [valid_ids[i:i + CARDS_PER_PAGE] for i in range(0, len(valid_ids), CARDS_PER_PAGE)]
    if not pages:
        pages = [[]]
    return render_template_string(PRINT_TEMPLATE, pages=pages)


@app.route("/")
def index() -> str:
    mappings = mapper.get_all_mappings()
    card_htmls = [_card_view_html(*m) for m in mappings]
    return render_template_string(PAGE_TEMPLATE, mappings=mappings, card_htmls=card_htmls)


@app.route("/now-playing")
def now_playing() -> Response:
    speaker_name = request.args.get("speaker")
    if not speaker_name:
        return jsonify(uri=None)
    try:
        target = SonosAPI(speaker_name)
        info = target.get_current_track_info()
    except Exception:
        info = {"uri": None}
    return jsonify(uri=info.get("uri"))


@app.route("/api/media-metadata", methods=["POST"])
def media_metadata() -> Response:
    data = request.get_json(silent=True) or {}
    url = data.get("url", "")
    if not url.startswith(("http://", "https://")):
        return jsonify(title=None)
    if url.startswith("https://open.spotify.com/"):
        oembed = fetch_spotify_oembed(url)
        if oembed:
            return jsonify(title=oembed.get("title"))
    return jsonify(title=None)


@app.route("/api/speakers")
def api_speakers() -> Response:
    try:
        speakers = soco.discover(timeout=5)
        if not speakers:
            return jsonify(speakers=[])
        return jsonify(speakers=sorted(s.player_name for s in speakers))
    except Exception:
        return jsonify(speakers=[])


@app.route("/mappings", methods=["POST"])
def add_mapping() -> Response:
    tag_uid = request.form.get("tag_uid", "").strip() or None
    media_uri = request.form.get("media_uri", "").strip()
    name = request.form.get("name", "").strip()
    shuffle = request.form.get("shuffle") == "on"
    if media_uri:
        mapping_id = mapper.create_mapping(media_uri, name, shuffle, tag_uid=tag_uid)
        if media_uri.startswith("https://open.spotify.com/"):
            image_data = fetch_spotify_artwork(media_uri)
            if image_data:
                mapper.upsert_image(mapping_id, image_data)
        flash(f"Mapping added for {name or tag_uid or 'new tag'}")
    return redirect(url_for("index"))


@app.route("/mappings/<int:mapping_id>/edit-form")
def edit_form(mapping_id: int) -> Response | tuple[Response, int]:
    mapping = mapper.get_mapping(mapping_id)
    if not mapping:
        return Response("mapping not found", status=404)
    return Response(_card_edit_html(*mapping))


@app.route("/mappings/<int:mapping_id>/card")
def card_view(mapping_id: int) -> Response | tuple[Response, int]:
    mapping = mapper.get_mapping(mapping_id)
    if not mapping:
        return Response("mapping not found", status=404)
    return Response(_card_view_html(*mapping))


@app.route("/mappings/<int:mapping_id>/edit", methods=["POST"])
def edit_mapping(mapping_id: int) -> Response | tuple[Response, int]:
    mapping = mapper.get_mapping(mapping_id)
    if not mapping:
        if _wants_html():
            return Response("mapping not found", status=404)
        return jsonify(error="mapping not found"), 404
    id_, old_name, old_shuffle, has_image = mapping.id, mapping.name, mapping.shuffle, mapping.has_image
    media_uri = request.form.get("media_uri", "").strip()
    name = request.form.get("name", "").strip()
    shuffle = request.form.get("shuffle") == "on"
    tag_uid = request.form.get("tag_uid", "").strip() or None
    if not media_uri:
        return Response(
            _card_edit_html(id_, tag_uid, "", name or old_name, old_shuffle, has_image, error="Media URI is required")
        )
    try:
        mapper.update_mapping(id_, media_uri, name, shuffle, tag_uid=tag_uid)
    except sqlite3.IntegrityError:
        return Response(
            _card_edit_html(id_, tag_uid, media_uri, name, shuffle, has_image,
                            error="This tag UID is already assigned to another mapping.")
        )
    if _wants_html():
        updated = mapper.get_mapping(id_)
        if not updated:
            return Response("mapping not found after save", status=500)
        return Response(_card_view_html(*updated))
    return redirect(url_for("index"))


@app.route("/mappings/<int:mapping_id>/delete", methods=["POST"])
def delete_mapping(mapping_id: int) -> Response:
    mapper.delete_mapping(mapping_id)
    flash("Mapping removed")
    return redirect(url_for("index"))


def _unknown_tags_html() -> str:
    """Return an HTML fragment for the unknown-tags section (or empty string)."""
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
            f'<div class="card-groove"></div>'
            f'<div class="card-body">'
            f'<div class="card-tag">{uid}</div>'
            f'<div class="card-uri">Scanned {count} {plural}</div>'
            f"</div>"
            f'<div class="card-actions">'
            f'<button type="button" class="btn btn-now-playing" data-tag-uid="{uid}"'
            f' @click="$refs.tagUid.value = $el.dataset.tagUid; $refs.tagUid.focus()">Use</button>'
            f"</div>"
            f"</div>"
        )
    return (
        f'<div class="section-head">'
        f"<h2>Recently Scanned</h2>"
        f'<span class="badge">{len(tags)}</span>'
        f"</div>"
        + "".join(cards)
    )


def _speaker_options_html() -> str:
    """Return <option> elements for discovered Sonos speakers."""
    try:
        speakers = soco.discover(timeout=5)
        if not speakers:
            return ""
        names = sorted(s.player_name for s in speakers)
        options = []
        for name in names:
            selected = " selected" if len(names) == 1 else ""
            options.append(f'<option value="{escape(name)}"{selected}>{escape(name)}</option>')
        return "\n".join(options)
    except Exception:
        return ""


def _thumb_html(mapping_id: int) -> str:
    """Return an <img> fragment for the given mapping's artwork."""
    src = url_for("get_image", mapping_id=mapping_id)
    return (
        f'<img id="thumb-{mapping_id}" class="card-thumb"'
        f' src="{src}?v={int(time.time())}"'
        f' alt="artwork" loading="lazy">'
    )


def _card_thumb_html(mapping_id: int, has_image: bool) -> str:
    """Return a thumbnail element for a card (img or placeholder)."""
    if has_image:
        return (
            f'<img id="thumb-{mapping_id}" class="card-thumb"'
            f' src="{url_for("get_image", mapping_id=mapping_id)}" alt="artwork" loading="lazy">'
        )
    return (
        f'<div id="thumb-{mapping_id}" class="card-thumb-placeholder"'
        f' title="No artwork">&#9835;</div>'
    )


def _card_view_html(mapping_id: int, tag_uid: str | None, media_uri: str, name: str, shuffle: bool, has_image: bool) -> str:
    """Return a view-mode card HTML fragment for the given mapping."""
    e_tag_uid = escape(tag_uid) if tag_uid else ""
    e_name = escape(name)
    e_media_uri = escape(media_uri)
    thumb = _card_thumb_html(mapping_id, has_image)

    display_name = e_name if name else (e_tag_uid if tag_uid else "Unnamed")
    shuffle_badge = ' <span class="badge-shuffle" title="Shuffle">&#x1F500;</span>' if shuffle else ""

    if tag_uid and name:
        tag_line = f'<div class="card-uri" title="{e_tag_uid}">{e_tag_uid}</div>'
    elif not tag_uid:
        tag_line = '<div class="card-uri" style="color:var(--muted);font-style:italic;">No tag assigned</div>'
    else:
        tag_line = ""

    if media_uri.upper() == "STOP":
        uri_line = '<div class="card-uri stop-cmd">&#9632; stop playback</div>'
    else:
        uri_line = f'<div class="card-uri" title="{e_media_uri}">{e_media_uri}</div>'

    edit_url = url_for("edit_form", mapping_id=mapping_id)

    return f"""<div class="card" id="card-{mapping_id}" x-data>
      <template x-if="$store.printMode.active">
        <div class="print-checkbox">
          <input type="checkbox"
                 {"disabled " + 'title="Capture artwork first"' if not has_image else ""}
                 @change='($event.target.checked ? $store.printMode.selected.add({mapping_id}) : $store.printMode.selected.delete({mapping_id}))'>
        </div>
      </template>
      {thumb}
      <div class="card-body">
        <div class="card-tag">{display_name}{shuffle_badge}</div>
        {tag_line}
        {uri_line}
      </div>
      <div class="card-actions" x-show="!$store.printMode.active">
        <button type="button" class="btn btn-edit"
                hx-get="{edit_url}"
                hx-target="#card-{mapping_id}"
                hx-swap="outerHTML">Edit</button>
      </div>
    </div>"""


def _card_edit_html(
    mapping_id: int, tag_uid: str | None, media_uri: str, name: str, shuffle: bool, has_image: bool, error: str | None = None
) -> str:
    """Return an edit-mode card HTML fragment for the given mapping."""
    e_tag_uid = escape(tag_uid or "")
    e_name = escape(name)
    e_media_uri = escape(media_uri)
    thumb = _card_thumb_html(mapping_id, has_image)

    edit_url = url_for("edit_mapping", mapping_id=mapping_id)
    card_url = url_for("card_view", mapping_id=mapping_id)
    delete_url = url_for("delete_mapping", mapping_id=mapping_id)
    image_url = url_for("set_image", mapping_id=mapping_id)

    checked = " checked" if shuffle else ""
    error_html = f'<div class="edit-error">{escape(error)}</div>' if error else ""

    return f"""<div class="card card-editing" id="card-{mapping_id}">
      {thumb}
      <div class="card-body">
        {error_html}
        <div class="edit-fields">
          <div class="form-field">
            <label>Name</label>
            <input type="text" name="name" value="{e_name}" placeholder="e.g. Kids playlist"
                   form="edit-form-{mapping_id}">
          </div>
          <div class="form-field"
               x-data="{{ waiting: false, since: '' }}"
               @assign-tag-found="$refs.tagUidInput.value = $event.detail.tag_uid; waiting = false">
            <label>Tag UID</label>
            <div style="display:flex; gap:0.4rem; align-items:center;">
              <input type="text" name="tag_uid" value="{e_tag_uid}" placeholder="e.g. 04:ab:cd:..."
                     x-ref="tagUidInput" form="edit-form-{mapping_id}">
              <button type="button" class="btn btn-save-url" x-show="!waiting"
                      @click="waiting = true; since = new Date().toISOString()">Assign tag</button>
              <template x-if="waiting">
                <div style="display:flex; gap:0.4rem; align-items:center;">
                  <span style="font-size:0.8rem; color:var(--muted); font-style:italic;">Scanning\u2026</span>
                  <div :hx-get="`/api/pending-tag?since=${{encodeURIComponent(since)}}`"
                       hx-trigger="load, every 1s"
                       hx-swap="none"
                       hx-on::after-request="if (event.detail.xhr.status === 200) this.dispatchEvent(new CustomEvent('assign-tag-found', {{bubbles: true, detail: JSON.parse(event.detail.xhr.responseText)}}))"
                       x-init="$nextTick(() => htmx.process($el))"></div>
                  <button type="button" class="btn btn-save-url" @click="waiting = false">Cancel</button>
                </div>
              </template>
            </div>
          </div>
          <div class="form-field">
            <label>Media URI</label>
            <input type="text" name="media_uri" value="{e_media_uri}" placeholder="Spotify link, Sonos URI, or STOP" required
                   form="edit-form-{mapping_id}">
          </div>
          <div class="form-field">
            <label>Shuffle</label>
            <div class="edit-checkbox-wrap">
              <input type="checkbox" id="shuffle-{mapping_id}" name="shuffle"{checked}
                     form="edit-form-{mapping_id}">
              <label for="shuffle-{mapping_id}">Play in shuffle mode</label>
            </div>
          </div>
        </div>
        <div class="edit-image-controls">
          <label>Cover Art</label>
          <div class="edit-image-row">
            <form hx-post="{image_url}"
                  hx-target="#thumb-{mapping_id}" hx-swap="outerHTML"
                  class="edit-image-url-form">
              <input type="text" name="image_url" placeholder="Image URL&hellip;">
              <button type="submit" class="btn btn-save-url">Load from URL</button>
            </form>
            <form hx-post="{image_url}"
                  hx-target="#thumb-{mapping_id}" hx-swap="outerHTML"
                  hx-encoding="multipart/form-data">
              <label class="btn btn-save-url" style="cursor:pointer;">
                File&hellip;
                <input type="file" name="image_file" accept="image/*" style="display:none"
                       onchange="this.form.requestSubmit()">
              </label>
            </form>
          </div>
        </div>
      </div>
      <div class="card-edit-footer">
        <div class="card-actions-edit">
          <form id="edit-form-{mapping_id}"
                hx-post="{edit_url}"
                hx-target="#card-{mapping_id}"
                hx-swap="outerHTML">
            <button type="submit" class="btn btn-primary btn-sm">Save</button>
          </form>
          <button type="button" class="btn btn-save-url"
                  hx-get="{card_url}"
                  hx-target="#card-{mapping_id}"
                  hx-swap="outerHTML">Cancel</button>
          <form method="post" action="{delete_url}" style="display:inline"
                hx-confirm="Delete this mapping?">
            <button type="submit" class="btn btn-delete">Delete mapping</button>
          </form>
        </div>
      </div>
    </div>"""


def _parse_image_payload() -> tuple[str | None, str | None, int]:
    """Extract image_data (base64) from the request. Returns (image_data, error, status)."""
    # Form submission: file upload or URL field
    if request.content_type and (
        "multipart/form-data" in request.content_type
        or "application/x-www-form-urlencoded" in request.content_type
    ):
        uploaded = request.files.get("image_file")
        if uploaded and uploaded.filename:
            raw = uploaded.read(MAX_IMAGE_SIZE + 1)
            if len(raw) > MAX_IMAGE_SIZE:
                return None, "image too large", 413
            return base64.b64encode(raw).decode("ascii"), None, 0
        image_url = request.form.get("image_url", "").strip()
        if image_url:
            image_data = fetch_image_as_base64(image_url)
            if not image_data:
                return None, "failed to fetch image", 502
            return image_data, None, 0
        return None, "missing image_url or image_file", 400

    # JSON API submission
    data = request.get_json(silent=True)
    if not data:
        return None, "missing image_url or image_data", 400
    if data.get("image_data", "").strip():
        image_data = data["image_data"].strip()
        try:
            raw = base64.b64decode(image_data)
        except Exception:
            return None, "invalid base64", 400
        if len(raw) > MAX_IMAGE_SIZE:
            return None, "image too large", 413
        return image_data, None, 0
    if data.get("image_url", "").strip():
        image_url = data["image_url"].strip()
        image_data = fetch_image_as_base64(image_url)
        if not image_data:
            return None, "failed to fetch image", 502
        return image_data, None, 0
    return None, "missing image_url or image_data", 400


def _wants_html() -> bool:
    """True if the request came from htmx or a browser form submission."""
    return "HX-Request" in request.headers


@app.route("/mappings/<int:mapping_id>/image", methods=["POST"])
def set_image(mapping_id: int) -> Response | tuple[Response, int]:
    image_data, error, status = _parse_image_payload()
    if error:
        if _wants_html():
            return Response(f"<span>{escape(error)}</span>", status=status)
        return jsonify(error=error), status
    assert image_data is not None
    if not mapper.upsert_image(mapping_id, image_data):
        if _wants_html():
            return Response("<span>mapping not found</span>", status=404)
        return jsonify(error="mapping not found"), 404
    if _wants_html():
        return Response(_thumb_html(mapping_id))
    return jsonify(ok=True)


@app.route("/mappings/<int:mapping_id>/image", methods=["GET"])
def get_image(mapping_id: int) -> Response | tuple[Response, int]:
    rows = mapper.get_mappings_with_images([mapping_id])
    if not rows:
        return jsonify(error="no image"), 404
    image_data = rows[0][1]
    etag = hashlib.sha256(image_data.encode()).hexdigest()
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304)
    raw = base64.b64decode(image_data)
    content_type = detect_image_content_type(raw)
    resp = Response(raw, content_type=content_type)
    resp.headers["ETag"] = etag
    resp.headers["Cache-Control"] = "public, no-cache"
    return resp


@app.route("/api/unknown-tags", methods=["POST"])
def api_post_unknown_tag() -> Response | tuple[Response, int]:
    data = request.get_json(silent=True)
    if not data or not data.get("tag_uid", "").strip():
        return jsonify(error="missing tag_uid"), 400
    unknown_tags.report(data["tag_uid"].strip())
    return jsonify(ok=True)


@app.route("/api/unknown-tags", methods=["GET"])
def api_get_unknown_tags() -> Response:
    return jsonify(tags=unknown_tags.get_all())


@app.route("/fragments/unknown-tags")
def fragment_unknown_tags() -> Response:
    return Response(_unknown_tags_html(), content_type="text/html")


@app.route("/fragments/speaker-options")
def fragment_speaker_options() -> Response:
    return Response(_speaker_options_html(), content_type="text/html")


@app.route("/api/mappings")
def api_mappings() -> Response:
    all_mappings = mapper.get_all_mappings()
    assigned = [m for m in all_mappings if m.tag_uid is not None]
    etag = mapper.compute_hash(assigned)
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304)
    resp = jsonify(
        mappings=[
            {"tag_uid": m.tag_uid, "media_uri": m.media_uri, "name": m.name, "shuffle": m.shuffle, "has_image": m.has_image}
            for m in assigned
        ]
    )
    resp.headers["ETag"] = etag
    return resp


@app.route("/api/pending-tag")
def api_pending_tag() -> Response | tuple[Response, int]:
    since = request.args.get("since")
    if not since:
        return jsonify(error="missing since"), 400
    entry = unknown_tags.get_since(since)
    if entry is None:
        return Response(status=204)
    return jsonify(tag_uid=entry["tag_uid"])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)
