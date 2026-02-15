import secrets
from typing import Optional

from flask import Flask, flash, jsonify, redirect, render_template_string, request, url_for
from markupsafe import escape
from werkzeug.wrappers import Response

from tontraeger.config import SONOS_SPEAKER_NAME
from tontraeger.sonos_api import SonosAPI
from tontraeger.tag_mapper import TagMapper

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

mapper = TagMapper()
sonos: Optional[SonosAPI] = None


def get_sonos() -> Optional[SonosAPI]:
    global sonos
    if sonos is None:
        try:
            sonos = SonosAPI(SONOS_SPEAKER_NAME)
        except Exception:
            return None
    return sonos

PAGE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>tontraeger</title>
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

  .form-field input {
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

  .form-field input:focus {
    outline: none;
    border-color: var(--amber);
  }

  .form-field input::placeholder {
    color: #4a4540;
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
    align-self: flex-end;
    margin-top: 0.3rem;
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

  /* ── Mappings list ───────────────────────── */
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

  .empty {
    text-align: center;
    color: var(--muted);
    padding: 3rem 1rem;
    font-style: italic;
    border: 1px dashed var(--border);
    border-radius: 10px;
  }

  /* ── Mapping cards ───────────────────────── */
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

  /* ── Responsive ──────────────────────────── */
  @media (max-width: 500px) {
    header h1 { font-size: 2rem; }
    .form-row { flex-direction: column; }
    .btn-primary { width: 100%; }
    .card { flex-wrap: wrap; gap: 0.6rem; }
    .card-groove { display: none; }
  }
</style>
</head>
<body>
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

  <div class="add-form">
    <h2>New Mapping</h2>
    <form method="post" action="{{ url_for('add_mapping') }}">
      <div class="form-row">
        <div class="form-field">
          <label for="name">Name</label>
          <input type="text" id="name" name="name" placeholder="e.g. Kids playlist">
        </div>
        <div class="form-field">
          <label for="tag_uid">Tag UID</label>
          <input type="text" id="tag_uid" name="tag_uid" placeholder="e.g. 123456789" required>
        </div>
        <div class="form-field">
          <label for="media_uri">Media URI</label>
          <input type="text" id="media_uri" name="media_uri" placeholder="Spotify link, Sonos URI, or STOP" required>
        </div>
        <button type="submit" class="btn btn-primary">Add</button>
        <button type="button" class="btn btn-now-playing" id="now-playing-btn" onclick="fetchNowPlaying()">Now Playing</button>
      </div>
    </form>
  </div>

  <div class="section-head">
    <h2>Mappings</h2>
    <span class="badge">{{ mappings|length }}</span>
  </div>

  {% if mappings %}
    {% for tag_uid, media_uri, name in mappings %}
    <div class="card">
      <div class="card-groove"></div>
      <div class="card-body">
        <div class="card-tag">{{ name if name else tag_uid }}</div>
        {% if name %}
          <div class="card-uri" title="{{ tag_uid }}">{{ tag_uid }}</div>
        {% endif %}
        {% if media_uri.upper() == 'STOP' %}
          <div class="card-uri stop-cmd">&#9632; stop playback</div>
        {% else %}
          <div class="card-uri" title="{{ media_uri }}">{{ media_uri }}</div>
        {% endif %}
      </div>
      <div class="card-actions">
        <form method="post" action="{{ url_for('delete_mapping', tag_uid=tag_uid) }}" style="display:inline"
              onsubmit="return confirm('Remove this mapping?')">
          <button type="submit" class="btn btn-delete">Remove</button>
        </form>
      </div>
    </div>
    {% endfor %}
  {% else %}
    <div class="empty">No mappings yet &mdash; scan a tag and add it above.</div>
  {% endif %}

  <footer>tontraeger &middot; Vinyl In, Sound Out</footer>

</div>
<script>
function fetchNowPlaying() {
  var btn = document.getElementById('now-playing-btn');
  var input = document.getElementById('media_uri');
  btn.classList.add('loading');
  btn.textContent = 'Fetching\u2026';
  fetch('{{ url_for("now_playing") }}')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.uri) {
        input.value = data.uri;
        input.focus();
      } else {
        btn.textContent = 'Nothing playing';
        setTimeout(function() { btn.textContent = 'Now Playing'; }, 2000);
      }
    })
    .catch(function() {
      btn.textContent = 'Error';
      setTimeout(function() { btn.textContent = 'Now Playing'; }, 2000);
    })
    .finally(function() { btn.classList.remove('loading'); });
}
</script>
</body>
</html>
"""


@app.route("/")
def index() -> str:
    mappings = mapper.get_all_mappings()
    return render_template_string(PAGE_TEMPLATE, mappings=mappings)


@app.route("/now-playing")
def now_playing() -> Response:
    active_sonos = sonos or get_sonos()
    if active_sonos is None:
        return jsonify(uri=None)

    try:
        uri = active_sonos.get_current_track_uri()
    except Exception:
        uri = None
    return jsonify(uri=uri)


@app.route("/mappings", methods=["POST"])
def add_mapping() -> Response:
    tag_uid = request.form.get("tag_uid", "").strip()
    media_uri = request.form.get("media_uri", "").strip()
    name = request.form.get("name", "").strip()
    if tag_uid and media_uri:
        mapper.insert_mapping(tag_uid, media_uri, name)
        flash(f"Mapping added for tag {escape(name or tag_uid)}")
    return redirect(url_for("index"))


@app.route("/mappings/<tag_uid>/delete", methods=["POST"])
def delete_mapping(tag_uid: str) -> Response:
    mapper.delete_mapping(tag_uid)
    flash(f"Mapping removed for tag {escape(tag_uid)}")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
