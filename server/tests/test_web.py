import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from flask.testing import FlaskClient

from tontraeger_server.tag_mapper import TagMapper
from tontraeger_server.web import app


@pytest.fixture
def client() -> FlaskClient:
    """Creates a test client backed by a temporary database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    test_mapper = TagMapper(db_path=path)

    # Patch the module-level mapper used by the routes.
    import tontraeger_server.web as web_module
    original = web_module.mapper
    web_module.mapper = test_mapper

    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client

    web_module.mapper = original
    os.remove(path)


@pytest.fixture(autouse=True)
def reset_unknown_tags() -> None:
    import tontraeger_server.web as web_module
    web_module.unknown_tags.clear()


def test_index_empty(client: FlaskClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"No mappings yet" in resp.data


def test_add_mapping(client: FlaskClient) -> None:
    resp = client.post("/mappings", data={"tag_uid": "111", "media_uri": "https://example.com", "name": "My Playlist"})
    assert resp.status_code == 302

    resp = client.get("/")
    assert b"My Playlist" in resp.data
    assert b"111" in resp.data
    assert b"https://example.com" in resp.data


def test_delete_mapping(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "222", "media_uri": "some_uri"})
    id_ = _get_mapping_id(client)

    resp = client.post(f"/mappings/{id_}/delete")
    assert resp.status_code == 302

    resp = client.get("/")
    assert b"some_uri" not in resp.data
    assert b'class="badge"' in resp.data
    assert b">0</span>" in resp.data


def test_add_empty_fields_ignored(client: FlaskClient) -> None:
    resp = client.post("/mappings", data={"tag_uid": "", "media_uri": ""})
    assert resp.status_code == 302

    resp = client.get("/")
    assert b"No mappings yet" in resp.data


def test_now_playing_without_speaker_returns_null(client: FlaskClient) -> None:
    resp = client.get("/now-playing")
    assert resp.status_code == 200
    assert resp.json == {"uri": None}


def test_api_unknown_tags_empty(client: FlaskClient) -> None:
    resp = client.get("/api/unknown-tags")
    assert resp.status_code == 200
    assert resp.json == {"tags": []}


def test_api_post_unknown_tag(client: FlaskClient) -> None:
    resp = client.post("/api/unknown-tags", json={"tag_uid": "abc123"})
    assert resp.status_code == 200

    resp = client.get("/api/unknown-tags")
    tags = resp.json["tags"]
    assert len(tags) == 1
    assert tags[0]["tag_uid"] == "abc123"
    assert tags[0]["scan_count"] == 1
    assert "first_seen" in tags[0]
    assert "last_seen" in tags[0]


def test_api_unknown_tag_dedup(client: FlaskClient) -> None:
    client.post("/api/unknown-tags", json={"tag_uid": "abc123"})
    resp1 = client.get("/api/unknown-tags")
    first_seen_1 = resp1.json["tags"][0]["first_seen"]

    client.post("/api/unknown-tags", json={"tag_uid": "abc123"})
    resp2 = client.get("/api/unknown-tags")
    tags = resp2.json["tags"]
    assert len(tags) == 1
    assert tags[0]["scan_count"] == 2
    assert tags[0]["first_seen"] == first_seen_1


def test_api_unknown_tag_fifo_eviction(client: FlaskClient) -> None:
    for i in range(21):
        client.post("/api/unknown-tags", json={"tag_uid": f"tag_{i:03d}"})

    resp = client.get("/api/unknown-tags")
    tags = resp.json["tags"]
    assert len(tags) == 20
    tag_uids = [t["tag_uid"] for t in tags]
    assert "tag_000" not in tag_uids
    assert "tag_001" in tag_uids
    assert "tag_020" in tag_uids


def test_api_post_unknown_tag_missing_uid(client: FlaskClient) -> None:
    resp = client.post("/api/unknown-tags", json={})
    assert resp.status_code == 400


def test_api_post_unknown_tag_empty_uid(client: FlaskClient) -> None:
    resp = client.post("/api/unknown-tags", json={"tag_uid": "  "})
    assert resp.status_code == 400


def test_api_post_unknown_tag_no_json(client: FlaskClient) -> None:
    resp = client.post("/api/unknown-tags", data="not json")
    assert resp.status_code == 400


# ── Fragment endpoints ──────────────────────────────────


def test_fragment_unknown_tags_empty(client: FlaskClient) -> None:
    resp = client.get("/fragments/unknown-tags")
    assert resp.status_code == 200
    assert resp.data == b""


def test_fragment_unknown_tags_with_tags(client: FlaskClient) -> None:
    client.post("/api/unknown-tags", json={"tag_uid": "AA:BB:CC"})
    resp = client.get("/fragments/unknown-tags")
    assert resp.status_code == 200
    assert b"AA:BB:CC" in resp.data
    assert b"Scanned 1 time" in resp.data
    assert b"Use" in resp.data


def test_fragment_unknown_tags_plural(client: FlaskClient) -> None:
    client.post("/api/unknown-tags", json={"tag_uid": "AA:BB:CC"})
    client.post("/api/unknown-tags", json={"tag_uid": "AA:BB:CC"})
    resp = client.get("/fragments/unknown-tags")
    assert b"Scanned 2 times" in resp.data


def test_fragment_speaker_options(client: FlaskClient) -> None:
    mock_speaker1 = MagicMock()
    mock_speaker1.player_name = "Kitchen"
    mock_speaker2 = MagicMock()
    mock_speaker2.player_name = "Bedroom"

    with patch("tontraeger_server.web.soco.discover", return_value=[mock_speaker1, mock_speaker2]):
        resp = client.get("/fragments/speaker-options")
        assert resp.status_code == 200
        assert b"Kitchen" in resp.data
        assert b"Bedroom" in resp.data
        assert b"selected" not in resp.data


def test_fragment_speaker_options_single_auto_selects(client: FlaskClient) -> None:
    mock_speaker = MagicMock()
    mock_speaker.player_name = "Kitchen"

    with patch("tontraeger_server.web.soco.discover", return_value=[mock_speaker]):
        resp = client.get("/fragments/speaker-options")
        assert resp.status_code == 200
        assert b"selected" in resp.data
        assert b"Kitchen" in resp.data


def test_fragment_speaker_options_none_found(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.soco.discover", return_value=None):
        resp = client.get("/fragments/speaker-options")
        assert resp.status_code == 200
        assert resp.data == b""


def test_fragment_speaker_options_discovery_error(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.soco.discover", side_effect=Exception("network error")):
        resp = client.get("/fragments/speaker-options")
        assert resp.status_code == 200
        assert resp.data == b""


def test_api_mappings_empty(client: FlaskClient) -> None:
    resp = client.get("/api/mappings")
    assert resp.status_code == 200
    assert resp.json == {"mappings": []}
    assert "ETag" in resp.headers


def test_api_mappings_with_data(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "aaa", "media_uri": "uri_a", "name": "Alpha"})
    client.post("/mappings", data={"tag_uid": "bbb", "media_uri": "uri_b", "name": ""})

    resp = client.get("/api/mappings")
    assert resp.status_code == 200
    assert len(resp.json["mappings"]) == 2
    assert resp.json["mappings"][0] == {"tag_uid": "aaa", "media_uri": "uri_a", "name": "Alpha", "shuffle": False, "has_image": False}
    assert resp.json["mappings"][1] == {"tag_uid": "bbb", "media_uri": "uri_b", "name": "", "shuffle": False, "has_image": False}


def test_add_mapping_with_shuffle(client: FlaskClient) -> None:
    resp = client.post("/mappings", data={"tag_uid": "333", "media_uri": "https://spotify.com/playlist", "name": "Radio", "shuffle": "on"})
    assert resp.status_code == 302

    resp = client.get("/api/mappings")
    assert resp.json["mappings"][0]["shuffle"] is True


def test_add_mapping_without_shuffle_defaults_false(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "444", "media_uri": "uri_d", "name": "Ordered"})

    resp = client.get("/api/mappings")
    assert resp.json["mappings"][0]["shuffle"] is False


def test_shuffle_badge_renders_in_html(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "s1", "media_uri": "uri", "name": "Radio", "shuffle": "on"})
    resp = client.get("/")
    assert b'class="badge-shuffle"' in resp.data


def test_shuffle_badge_absent_without_shuffle(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "s2", "media_uri": "uri", "name": "Ordered"})
    resp = client.get("/")
    assert b'class="badge-shuffle"' not in resp.data


def test_etag_changes_on_shuffle_toggle(client: FlaskClient) -> None:
    """Toggling shuffle on a mapping must invalidate the ETag."""
    client.post("/mappings", data={"tag_uid": "aaa", "media_uri": "uri_a", "name": ""})
    id_ = _get_mapping_id(client)
    resp1 = client.get("/api/mappings")
    old_etag = resp1.headers["ETag"]

    # Update the mapping with shuffle=True via the edit endpoint
    client.post(f"/mappings/{id_}/edit", data={"tag_uid": "aaa", "media_uri": "uri_a", "name": "", "shuffle": "on"}, headers=HX_HEADERS)
    resp2 = client.get("/api/mappings", headers={"If-None-Match": old_etag})
    assert resp2.status_code == 200
    assert resp2.headers["ETag"] != old_etag
    assert resp2.json["mappings"][0]["shuffle"] is True


def test_api_mappings_etag_304(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "aaa", "media_uri": "uri_a", "name": ""})
    resp1 = client.get("/api/mappings")
    etag = resp1.headers["ETag"]

    resp2 = client.get("/api/mappings", headers={"If-None-Match": etag})
    assert resp2.status_code == 304


def test_api_mappings_etag_200_after_change(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "aaa", "media_uri": "uri_a", "name": ""})
    resp1 = client.get("/api/mappings")
    old_etag = resp1.headers["ETag"]

    client.post("/mappings", data={"tag_uid": "bbb", "media_uri": "uri_b", "name": ""})
    resp2 = client.get("/api/mappings", headers={"If-None-Match": old_etag})
    assert resp2.status_code == 200
    assert len(resp2.json["mappings"]) == 2
    assert resp2.headers["ETag"] != old_etag


def test_api_mappings_wrong_etag_returns_200(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "aaa", "media_uri": "uri_a", "name": ""})
    resp = client.get("/api/mappings", headers={"If-None-Match": "wrong-etag"})
    assert resp.status_code == 200
    assert len(resp.json["mappings"]) == 1


def test_template_alpine_and_htmx_wired(client: FlaskClient) -> None:
    """Verify the template uses Alpine.js and htmx correctly."""
    html = client.get("/").data.decode()
    # CDN scripts loaded
    assert "alpinejs" in html
    assert "htmx.org" in html
    # htmx boost on body
    assert 'hx-boost="true"' in html
    # Alpine component
    assert 'x-data="formHelper()"' in html
    assert '@click="fetchNowPlaying()"' in html
    # Input refs
    assert 'x-ref="mediaUri"' in html
    assert 'x-ref="tagUid"' in html
    # Speaker picker (htmx-loaded options, Alpine for model binding)
    assert 'x-model="selectedSpeaker"' in html
    assert "/fragments/speaker-options" in html
    # Unknown tags section (htmx polling)
    assert "/fragments/unknown-tags" in html
    assert 'hx-trigger="load, every 5s"' in html


def test_api_speakers(client: FlaskClient) -> None:
    mock_speaker1 = MagicMock()
    mock_speaker1.player_name = "Kitchen"
    mock_speaker2 = MagicMock()
    mock_speaker2.player_name = "Bedroom"

    with patch("tontraeger_server.web.soco.discover", return_value=[mock_speaker1, mock_speaker2]):
        resp = client.get("/api/speakers")
        assert resp.status_code == 200
        assert resp.json == {"speakers": ["Bedroom", "Kitchen"]}


def test_api_speakers_none_found(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.soco.discover", return_value=None):
        resp = client.get("/api/speakers")
        assert resp.json == {"speakers": []}


def test_api_speakers_discovery_error(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.soco.discover", side_effect=Exception("network error")):
        resp = client.get("/api/speakers")
        assert resp.json == {"speakers": []}


def test_now_playing_with_speaker_param(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.SonosAPI") as MockSonosAPI:
        mock_instance = MagicMock()
        mock_instance.get_current_track_info.return_value = {"uri": "x-radio:123"}
        MockSonosAPI.return_value = mock_instance

        resp = client.get("/now-playing?speaker=Kitchen")
        assert resp.status_code == 200
        assert resp.json == {"uri": "x-radio:123"}
        MockSonosAPI.assert_called_once_with("Kitchen")


def test_now_playing_with_unknown_speaker(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.SonosAPI", side_effect=Exception("not found")):
        resp = client.get("/now-playing?speaker=Nonexistent")
        assert resp.json == {"uri": None}




def _get_mapping_id(client: FlaskClient, index: int = 0) -> int:
    """Helper: return the id of the nth mapping (0-indexed)."""
    import tontraeger_server.web as web_module
    return web_module.mapper.get_all_mappings()[index][0]


# ── Image routes ──────────────────────────────────────


def test_set_image(client: FlaskClient) -> None:
    import base64
    jpeg_stub = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 20).decode("ascii")

    client.post("/mappings", data={"tag_uid": "img1", "media_uri": "uri_a"})
    id_ = _get_mapping_id(client)
    with patch("tontraeger_server.web.fetch_image_as_base64", return_value=jpeg_stub):
        resp = client.post(f"/mappings/{id_}/image", json={"image_url": "http://example.com/art.jpg"})
    assert resp.status_code == 200
    assert resp.json == {"ok": True}

    resp = client.get(f"/mappings/{id_}/image")
    assert resp.status_code == 200
    assert resp.content_type == "image/jpeg"


def test_set_image_via_base64_upload(client: FlaskClient) -> None:
    import base64
    jpeg_stub = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 20).decode("ascii")

    client.post("/mappings", data={"tag_uid": "img_up", "media_uri": "uri_up"})
    id_ = _get_mapping_id(client)
    resp = client.post(f"/mappings/{id_}/image", json={"image_data": jpeg_stub})
    assert resp.status_code == 200
    assert resp.json == {"ok": True}

    resp = client.get(f"/mappings/{id_}/image")
    assert resp.status_code == 200
    assert resp.content_type == "image/jpeg"


def test_set_image_invalid_base64(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "bad64", "media_uri": "uri"})
    id_ = _get_mapping_id(client)
    resp = client.post(f"/mappings/{id_}/image", json={"image_data": "not!valid!base64!"})
    assert resp.status_code == 400
    assert resp.json["error"] == "invalid base64"


def test_set_image_too_large(client: FlaskClient) -> None:
    import base64
    import tontraeger_server.web as web_module
    original_max = web_module.MAX_IMAGE_SIZE
    web_module.MAX_IMAGE_SIZE = 100  # 100 bytes for test
    try:
        client.post("/mappings", data={"tag_uid": "big1", "media_uri": "uri"})
        id_ = _get_mapping_id(client)
        large_data = base64.b64encode(b"\xff\xd8" + b"\x00" * 200).decode("ascii")
        resp = client.post(f"/mappings/{id_}/image", json={"image_data": large_data})
        assert resp.status_code == 413
        assert resp.json["error"] == "image too large"
    finally:
        web_module.MAX_IMAGE_SIZE = original_max


HX_HEADERS = {"HX-Request": "true"}


def test_set_image_form_url(client: FlaskClient) -> None:
    import base64
    jpeg_stub = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 20).decode("ascii")

    client.post("/mappings", data={"tag_uid": "furl1", "media_uri": "uri"})
    id_ = _get_mapping_id(client)
    with patch("tontraeger_server.web.fetch_image_as_base64", return_value=jpeg_stub):
        resp = client.post(f"/mappings/{id_}/image", data={"image_url": "http://example.com/art.jpg"}, headers=HX_HEADERS)
    assert resp.status_code == 200
    assert b"<img" in resp.data
    assert f'id="thumb-{id_}"'.encode() in resp.data

    resp = client.get(f"/mappings/{id_}/image")
    assert resp.status_code == 200
    assert resp.content_type == "image/jpeg"


def test_set_image_form_integer_id_in_html(client: FlaskClient) -> None:
    """After set_image, returned HTML uses integer-based IDs."""
    import base64
    jpeg_stub = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 20).decode("ascii")

    client.post("/mappings", data={"tag_uid": "04:3d:24:82", "media_uri": "uri"})
    id_ = _get_mapping_id(client)
    with patch("tontraeger_server.web.fetch_image_as_base64", return_value=jpeg_stub):
        resp = client.post(f"/mappings/{id_}/image", data={"image_url": "http://example.com/art.jpg"}, headers=HX_HEADERS)
    assert resp.status_code == 200
    assert f'id="thumb-{id_}"'.encode() in resp.data

    # Main page and edit form use integer-based IDs
    resp = client.get("/")
    assert f'id="thumb-{id_}"'.encode() in resp.data
    assert f'id="card-{id_}"'.encode() in resp.data

    # Edit form has hx-target with integer-based ID for image upload
    resp = client.get(f"/mappings/{id_}/edit-form")
    assert f'hx-target="#thumb-{id_}"'.encode() in resp.data


def test_set_image_form_file_upload(client: FlaskClient) -> None:
    import io

    client.post("/mappings", data={"tag_uid": "fup1", "media_uri": "uri"})
    id_ = _get_mapping_id(client)
    data = {"image_file": (io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 20), "photo.jpg")}
    resp = client.post(f"/mappings/{id_}/image", data=data, content_type="multipart/form-data", headers=HX_HEADERS)
    assert resp.status_code == 200
    assert b"<img" in resp.data
    assert f'id="thumb-{id_}"'.encode() in resp.data

    resp = client.get(f"/mappings/{id_}/image")
    assert resp.status_code == 200
    assert resp.content_type == "image/jpeg"


def test_set_image_form_file_too_large(client: FlaskClient) -> None:
    import io
    import tontraeger_server.web as web_module
    original_max = web_module.MAX_IMAGE_SIZE
    web_module.MAX_IMAGE_SIZE = 100
    try:
        client.post("/mappings", data={"tag_uid": "fbig", "media_uri": "uri"})
        id_ = _get_mapping_id(client)
        data = {"image_file": (io.BytesIO(b"\xff\xd8" + b"\x00" * 200), "big.jpg")}
        resp = client.post(f"/mappings/{id_}/image", data=data, content_type="multipart/form-data", headers=HX_HEADERS)
        assert resp.status_code == 413
        assert b"image too large" in resp.data
    finally:
        web_module.MAX_IMAGE_SIZE = original_max


def test_set_image_form_nonexistent_mapping(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.fetch_image_as_base64", return_value="base64data"):
        resp = client.post("/mappings/99999/image", data={"image_url": "http://example.com/art.jpg"}, headers=HX_HEADERS)
    assert resp.status_code == 404
    assert b"<span>" in resp.data
    assert b"mapping not found" in resp.data


def test_set_image_form_missing_fields(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "fmiss", "media_uri": "uri"})
    id_ = _get_mapping_id(client)
    resp = client.post(f"/mappings/{id_}/image", data={}, headers=HX_HEADERS)
    assert resp.status_code == 400
    assert b"<span>" in resp.data


def test_set_image_json_still_returns_json(client: FlaskClient) -> None:
    """JSON POST without HX-Request header returns JSON, not HTML."""
    import base64
    jpeg_stub = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 20).decode("ascii")

    client.post("/mappings", data={"tag_uid": "jsoncheck", "media_uri": "uri"})
    id_ = _get_mapping_id(client)
    with patch("tontraeger_server.web.fetch_image_as_base64", return_value=jpeg_stub):
        resp = client.post(f"/mappings/{id_}/image", json={"image_url": "http://example.com/art.jpg"})
    assert resp.status_code == 200
    assert resp.json == {"ok": True}


def test_set_image_missing_url(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "img2", "media_uri": "uri_b"})
    id_ = _get_mapping_id(client)
    resp = client.post(f"/mappings/{id_}/image", json={})
    assert resp.status_code == 400


def test_set_image_fetch_fails(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "img3", "media_uri": "uri_c"})
    id_ = _get_mapping_id(client)
    with patch("tontraeger_server.web.fetch_image_as_base64", return_value=None):
        resp = client.post(f"/mappings/{id_}/image", json={"image_url": "http://bad.url/nope"})
    assert resp.status_code == 502


def test_set_image_nonexistent_mapping(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.fetch_image_as_base64", return_value="base64data"):
        resp = client.post("/mappings/99999/image", json={"image_url": "http://example.com/art.jpg"})
    assert resp.status_code == 404


def test_get_image_no_image(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "noimg", "media_uri": "uri_d"})
    id_ = _get_mapping_id(client)
    resp = client.get(f"/mappings/{id_}/image")
    assert resp.status_code == 404


def test_get_image_etag(client: FlaskClient) -> None:
    import base64
    jpeg_stub = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 20).decode("ascii")

    client.post("/mappings", data={"tag_uid": "etag1", "media_uri": "uri"})
    import tontraeger_server.web as web_module
    id_ = _get_mapping_id(client)
    web_module.mapper.upsert_image(id_, jpeg_stub)

    resp1 = client.get(f"/mappings/{id_}/image")
    assert resp1.status_code == 200
    assert "ETag" in resp1.headers
    etag = resp1.headers["ETag"]

    # Same ETag returns 304
    resp2 = client.get(f"/mappings/{id_}/image", headers={"If-None-Match": etag})
    assert resp2.status_code == 304

    # After updating image, old ETag returns 200 with new ETag
    new_stub = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20).decode("ascii")
    web_module.mapper.upsert_image(id_, new_stub)
    resp3 = client.get(f"/mappings/{id_}/image", headers={"If-None-Match": etag})
    assert resp3.status_code == 200
    assert resp3.headers["ETag"] != etag


def test_get_image_detects_png(client: FlaskClient) -> None:
    import base64
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    b64 = base64.b64encode(png_header).decode("ascii")

    client.post("/mappings", data={"tag_uid": "png1", "media_uri": "uri_e"})
    import tontraeger_server.web as web_module
    id_ = _get_mapping_id(client)
    web_module.mapper.upsert_image(id_, b64)

    resp = client.get(f"/mappings/{id_}/image")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"


def test_add_mapping_auto_fetches_spotify_artwork(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.fetch_spotify_artwork", return_value="spotify_art_b64") as mock_fetch:
        client.post("/mappings", data={
            "tag_uid": "spot1",
            "media_uri": "https://open.spotify.com/album/abc123",
            "name": "My Album",
        })
        mock_fetch.assert_called_once_with("https://open.spotify.com/album/abc123")

    resp = client.get("/api/mappings")
    assert resp.json["mappings"][0]["has_image"] is True


def test_add_mapping_spotify_artwork_failure_still_creates_mapping(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.fetch_spotify_artwork", return_value=None):
        client.post("/mappings", data={
            "tag_uid": "spot2",
            "media_uri": "https://open.spotify.com/playlist/xyz",
            "name": "Playlist",
        })

    resp = client.get("/api/mappings")
    assert len(resp.json["mappings"]) == 1
    assert resp.json["mappings"][0]["has_image"] is False


def test_add_mapping_non_spotify_no_auto_fetch(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.fetch_spotify_artwork") as mock_fetch:
        client.post("/mappings", data={
            "tag_uid": "radio1",
            "media_uri": "x-sonosapi-radio:s25111",
            "name": "Radio",
        })
        mock_fetch.assert_not_called()


# ── Media metadata ────────────────────────────────────


def test_media_metadata_spotify_url_returns_title(client: FlaskClient) -> None:
    oembed_response = {"title": "Beatles - Abbey Road", "thumbnail_url": "https://example.com/img.jpg"}
    with patch("tontraeger_server.web.fetch_spotify_oembed", return_value=oembed_response):
        resp = client.post("/api/media-metadata", json={"url": "https://open.spotify.com/album/abc123"})
    assert resp.status_code == 200
    assert resp.json["title"] == "Beatles - Abbey Road"


def test_media_metadata_non_spotify_url_returns_null(client: FlaskClient) -> None:
    resp = client.post("/api/media-metadata", json={"url": "https://example.com/something"})
    assert resp.status_code == 200
    assert resp.json["title"] is None


def test_media_metadata_non_url_returns_null(client: FlaskClient) -> None:
    resp = client.post("/api/media-metadata", json={"url": "x-sonosapi-radio:s25111"})
    assert resp.status_code == 200
    assert resp.json["title"] is None


def test_media_metadata_stop_returns_null(client: FlaskClient) -> None:
    resp = client.post("/api/media-metadata", json={"url": "STOP"})
    assert resp.status_code == 200
    assert resp.json["title"] is None


def test_media_metadata_empty_url_returns_null(client: FlaskClient) -> None:
    resp = client.post("/api/media-metadata", json={"url": ""})
    assert resp.status_code == 200
    assert resp.json["title"] is None


def test_media_metadata_no_body_returns_null(client: FlaskClient) -> None:
    resp = client.post("/api/media-metadata", content_type="application/json")
    assert resp.status_code == 200
    assert resp.json["title"] is None


def test_media_metadata_oembed_failure_returns_null(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.fetch_spotify_oembed", return_value=None):
        resp = client.post("/api/media-metadata", json={"url": "https://open.spotify.com/album/abc123"})
    assert resp.status_code == 200
    assert resp.json["title"] is None


def test_media_metadata_oembed_missing_title_returns_null(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.fetch_spotify_oembed", return_value={}):
        resp = client.post("/api/media-metadata", json={"url": "https://open.spotify.com/album/abc123"})
    assert resp.status_code == 200
    assert resp.json["title"] is None


# ── Edit mappings ─────────────────────────────────────


def test_edit_form_get(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "e1", "media_uri": "uri_a", "name": "Alpha", "shuffle": "on"})
    id_ = _get_mapping_id(client)

    resp = client.get(f"/mappings/{id_}/edit-form")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert f'id="card-{id_}"' in html
    assert 'value="Alpha"' in html
    assert 'value="uri_a"' in html
    assert "checked" in html
    assert "Save" in html
    assert "Cancel" in html
    assert "Delete mapping" in html
    assert 'hx-confirm="Delete this mapping?"' in html


def test_edit_form_get_nonexistent(client: FlaskClient) -> None:
    resp = client.get("/mappings/99999/edit-form")
    assert resp.status_code == 404


def test_card_get(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "c1", "media_uri": "uri_c", "name": "CardTest"})
    id_ = _get_mapping_id(client)

    resp = client.get(f"/mappings/{id_}/card")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert f'id="card-{id_}"' in html
    assert "CardTest" in html
    assert "Edit" in html


def test_card_get_nonexistent(client: FlaskClient) -> None:
    resp = client.get("/mappings/99999/card")
    assert resp.status_code == 404


def test_edit_mapping(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "ed1", "media_uri": "old_uri", "name": "Old Name"})
    id_ = _get_mapping_id(client)

    resp = client.post(
        f"/mappings/{id_}/edit",
        data={"tag_uid": "ed1", "name": "New Name", "media_uri": "new_uri", "shuffle": "on"},
        headers=HX_HEADERS,
    )
    assert resp.status_code == 200
    html = resp.data.decode()
    assert "New Name" in html
    assert "new_uri" in html
    assert f'id="card-{id_}"' in html
    # Should be back in view mode (has Edit button, not Save)
    assert "Edit" in html

    # Verify the data was actually saved
    resp = client.get("/api/mappings")
    m = resp.json["mappings"][0]
    assert m["name"] == "New Name"
    assert m["media_uri"] == "new_uri"
    assert m["shuffle"] is True


def test_edit_mapping_empty_uri(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "ed2", "media_uri": "valid_uri", "name": "Test"})
    id_ = _get_mapping_id(client)

    resp = client.post(
        f"/mappings/{id_}/edit",
        data={"name": "Test", "media_uri": "", "shuffle": ""},
        headers=HX_HEADERS,
    )
    assert resp.status_code == 200
    html = resp.data.decode()
    # Should stay in edit mode with error
    assert "Media URI is required" in html
    assert "card-editing" in html

    # Original data should be unchanged
    resp = client.get("/api/mappings")
    assert resp.json["mappings"][0]["media_uri"] == "valid_uri"


def test_edit_mapping_nonexistent(client: FlaskClient) -> None:
    resp = client.post(
        "/mappings/99999/edit",
        data={"name": "x", "media_uri": "y"},
        headers=HX_HEADERS,
    )
    assert resp.status_code == 404


def test_edit_mapping_preserves_image(client: FlaskClient) -> None:
    import base64
    import tontraeger_server.web as web_module

    jpeg_stub = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 20).decode("ascii")
    client.post("/mappings", data={"tag_uid": "ed3", "media_uri": "old_uri", "name": "Img Test"})
    id_ = _get_mapping_id(client)
    web_module.mapper.upsert_image(id_, jpeg_stub)

    # Edit the mapping
    client.post(
        f"/mappings/{id_}/edit",
        data={"tag_uid": "ed3", "name": "Updated", "media_uri": "new_uri"},
        headers=HX_HEADERS,
    )

    # Image should still be there
    resp = client.get(f"/mappings/{id_}/image")
    assert resp.status_code == 200
    assert resp.content_type == "image/jpeg"


def test_edit_form_uses_integer_id_not_uid(client: FlaskClient) -> None:
    """Edit form uses integer-based IDs, not tag UID."""
    client.post("/mappings", data={"tag_uid": "04:ab:cd", "media_uri": "uri"})
    id_ = _get_mapping_id(client)

    resp = client.get(f"/mappings/{id_}/edit-form")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert f'id="card-{id_}"' in html
    assert f'id="thumb-{id_}"' in html


def test_index_shows_edit_button(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "idx1", "media_uri": "uri_a", "name": "Test"})
    id_ = _get_mapping_id(client)
    resp = client.get("/")
    html = resp.data.decode()
    assert "Edit" in html
    assert f'id="card-{id_}"' in html
    # Should NOT have the delete button in view mode
    assert "Delete mapping" not in html


# ── Print view ────────────────────────────────────────


def test_print_view_renders_cards(client: FlaskClient) -> None:
    import base64
    import tontraeger_server.web as web_module
    jpeg_stub = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 20).decode("ascii")

    client.post("/mappings", data={"tag_uid": "p1", "media_uri": "uri_a"})
    client.post("/mappings", data={"tag_uid": "p2", "media_uri": "uri_b"})
    mappings = web_module.mapper.get_all_mappings()
    id1, id2 = mappings[0][0], mappings[1][0]
    web_module.mapper.upsert_image(id1, jpeg_stub)
    web_module.mapper.upsert_image(id2, jpeg_stub)

    resp = client.get(f"/print?id={id1}&id={id2}")
    assert resp.status_code == 200
    assert f"/mappings/{id1}/image".encode() in resp.data
    assert f"/mappings/{id2}/image".encode() in resp.data
    assert b"59mm" in resp.data
    assert b"card-outline" in resp.data


def test_print_view_skips_missing_images(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "noart", "media_uri": "uri_c"})
    id_ = _get_mapping_id(client)

    resp = client.get(f"/print?id={id_}")
    assert resp.status_code == 200
    assert f"/mappings/{id_}/image".encode() not in resp.data


def test_print_view_empty_selection(client: FlaskClient) -> None:
    resp = client.get("/print")
    assert resp.status_code == 200
    assert b"100%" in resp.data


def test_print_view_ignores_nonexistent_ids(client: FlaskClient) -> None:
    resp = client.get("/print?id=99998&id=99999")
    assert resp.status_code == 200
    assert b"/mappings/99998/image" not in resp.data


# ── New behavior: surrogate PKs + tap-to-assign ───────


def test_add_mapping_without_uid(client: FlaskClient) -> None:
    resp = client.post("/mappings", data={"media_uri": "https://example.com", "name": "No Tag Yet"})
    assert resp.status_code == 302

    resp = client.get("/")
    assert b"No Tag Yet" in resp.data
    assert b"No tag" in resp.data  # unassigned indicator


def test_edit_mapping_changes_uid(client: FlaskClient) -> None:
    client.post("/mappings", data={"media_uri": "uri_a", "name": "Alpha"})
    id_ = _get_mapping_id(client)

    resp = client.post(
        f"/mappings/{id_}/edit",
        data={"name": "Alpha", "media_uri": "uri_a", "tag_uid": "04:ab:cd"},
        headers=HX_HEADERS,
    )
    assert resp.status_code == 200

    resp = client.get("/api/mappings")
    assert len(resp.json["mappings"]) == 1
    assert resp.json["mappings"][0]["tag_uid"] == "04:ab:cd"


def test_edit_mapping_clears_uid(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "aa:bb", "media_uri": "uri_a", "name": "Alpha"})
    id_ = _get_mapping_id(client)

    client.post(
        f"/mappings/{id_}/edit",
        data={"name": "Alpha", "media_uri": "uri_a", "tag_uid": ""},
        headers=HX_HEADERS,
    )

    resp = client.get("/api/mappings")
    assert resp.json["mappings"] == []  # now unassigned, excluded from API


def test_edit_mapping_duplicate_uid_error(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "uid1", "media_uri": "uri_a"})
    client.post("/mappings", data={"media_uri": "uri_b"})
    id2 = _get_mapping_id(client, index=1)

    resp = client.post(
        f"/mappings/{id2}/edit",
        data={"name": "", "media_uri": "uri_b", "tag_uid": "uid1"},
        headers=HX_HEADERS,
    )
    assert resp.status_code == 200
    assert b"already assigned" in resp.data
    assert b"card-editing" in resp.data  # stayed in edit mode


def test_card_view_unassigned_shows_indicator(client: FlaskClient) -> None:
    client.post("/mappings", data={"media_uri": "uri_a", "name": "Pending"})
    id_ = _get_mapping_id(client)

    resp = client.get(f"/mappings/{id_}/card")
    assert resp.status_code == 200
    assert b"No tag" in resp.data


def test_api_mappings_excludes_unassigned(client: FlaskClient) -> None:
    client.post("/mappings", data={"media_uri": "uri_a", "name": "No Tag"})
    client.post("/mappings", data={"tag_uid": "has-uid", "media_uri": "uri_b", "name": "Has Tag"})

    resp = client.get("/api/mappings")
    assert resp.status_code == 200
    assert len(resp.json["mappings"]) == 1
    assert resp.json["mappings"][0]["tag_uid"] == "has-uid"


def test_api_mappings_etag_stable_on_unassigned_change(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "uid1", "media_uri": "uri_a"})
    etag1 = client.get("/api/mappings").headers["ETag"]

    # Add an unassigned mapping — should not change the ETag
    client.post("/mappings", data={"media_uri": "uri_b"})
    etag2 = client.get("/api/mappings").headers["ETag"]

    assert etag1 == etag2


def test_api_mappings_response_has_no_id_field(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "aaa", "media_uri": "uri_a"})
    resp = client.get("/api/mappings")
    assert resp.status_code == 200
    mapping = resp.json["mappings"][0]
    assert "id" not in mapping
    assert set(mapping.keys()) == {"tag_uid", "media_uri", "name", "shuffle", "has_image"}


def test_pending_tag_no_result(client: FlaskClient) -> None:
    resp = client.get("/api/pending-tag?since=2099-01-01T00:00:00.000Z")
    assert resp.status_code == 204


def test_pending_tag_missing_since(client: FlaskClient) -> None:
    resp = client.get("/api/pending-tag")
    assert resp.status_code == 400


def test_pending_tag_returns_uid(client: FlaskClient) -> None:
    since = "2000-01-01T00:00:00.000Z"
    client.post("/api/unknown-tags", json={"tag_uid": "04:ab:cd"})
    resp = client.get(f"/api/pending-tag?since={since}")
    assert resp.status_code == 200
    assert resp.json["tag_uid"] == "04:ab:cd"


def test_pending_tag_z_suffix_normalized(client: FlaskClient) -> None:
    """Z-suffixed 'since' compares correctly with server's +00:00 timestamps.

    JS sends since = new Date().toISOString() → "2026-03-24T10:30:00.123Z"
    Server stores last_seen via datetime.now(timezone.utc).isoformat() → "2026-03-24T10:30:00.123456+00:00"
    Without normalization, "123456+00:00" < "123Z" ('+' < 'Z' in ASCII), causing
    false negatives for tags scanned within the same millisecond as since.
    """
    import tontraeger_server.web as web_module

    client.post("/api/unknown-tags", json={"tag_uid": "04:ab:cd"})
    entry = web_module.unknown_tags.get_all()[0]
    last_seen = entry["last_seen"]  # e.g. "2026-03-24T10:30:00.123456+00:00"

    # Construct a Z-suffixed since equal to the same millisecond.
    # last_seen[:23] = "2026-03-24T10:30:00.123" (truncated to ms precision)
    since_z = last_seen[:23] + "Z"

    resp = client.get(f"/api/pending-tag?since={since_z}")
    # Without the fix, "123456+00:00" > "123Z" is False → 204 (tag not found).
    # With the fix (Z → +00:00), "123456+00:00" > "123+00:00" is True → 200.
    assert resp.status_code == 200
    assert resp.json["tag_uid"] == "04:ab:cd"


# ── Filter unassigned ─────────────────────────────────


def test_card_view_unassigned_has_data_attribute(client: FlaskClient) -> None:
    """Card for mapping without tag_uid includes data-unassigned attribute."""
    client.post("/mappings", data={"media_uri": "uri_a", "name": "No Tag"})
    id_ = _get_mapping_id(client)

    resp = client.get(f"/mappings/{id_}/card")
    assert resp.status_code == 200
    assert b"data-unassigned" in resp.data


def test_card_view_assigned_lacks_data_attribute(client: FlaskClient) -> None:
    """Card for mapping with tag_uid does NOT include data-unassigned attribute."""
    client.post("/mappings", data={"tag_uid": "abc", "media_uri": "uri_b", "name": "Has Tag"})
    id_ = _get_mapping_id(client)

    resp = client.get(f"/mappings/{id_}/card")
    assert resp.status_code == 200
    assert b"data-unassigned" not in resp.data


def test_index_includes_filter_counts_in_store(client: FlaskClient) -> None:
    """Index page embeds totalCount and unassignedCount on the card-list element.

    Counts must be in x-init on #card-list (not in the alpine:init script)
    so they update on htmx body swaps when mappings are added/removed.
    """
    client.post("/mappings", data={"tag_uid": "t1", "media_uri": "uri_1"})
    client.post("/mappings", data={"tag_uid": "t2", "media_uri": "uri_2"})
    client.post("/mappings", data={"media_uri": "uri_3", "name": "Pending"})

    resp = client.get("/")
    html = resp.data.decode()
    assert "totalCount = 3" in html
    assert "unassignedCount = 1" in html
    # Counts must be in x-init on the card-list div (swappable DOM), not in script
    card_list_start = html.index('id="card-list"')
    card_list_tag = html[card_list_start : html.index(">", card_list_start)]
    assert "x-init" in card_list_tag
    assert "totalCount = 3" in card_list_tag


def test_index_renders_filter_toggle_button(client: FlaskClient) -> None:
    """Index page contains the unassigned filter toggle button."""
    client.post("/mappings", data={"tag_uid": "x", "media_uri": "uri"})

    resp = client.get("/")
    assert b"Show unassigned" in resp.data


def test_index_card_list_has_id(client: FlaskClient) -> None:
    """The card list container has id='card-list' for CSS filter targeting."""
    client.post("/mappings", data={"tag_uid": "x", "media_uri": "uri"})

    resp = client.get("/")
    assert b'id="card-list"' in resp.data


def test_index_filter_css_rule_present(client: FlaskClient) -> None:
    """The page includes the CSS rule for hiding non-unassigned cards."""
    resp = client.get("/")
    assert b".filter-unassigned" in resp.data
