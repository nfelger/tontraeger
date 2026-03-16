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

    resp = client.post("/mappings/222/delete")
    assert resp.status_code == 302

    resp = client.get("/")
    assert b"some_uri" not in resp.data
    assert b'<span class="badge">0</span>' in resp.data


def test_add_empty_fields_ignored(client: FlaskClient) -> None:
    resp = client.post("/mappings", data={"tag_uid": "", "media_uri": ""})
    assert resp.status_code == 302

    resp = client.get("/")
    assert b"No mappings yet" in resp.data


def test_now_playing_returns_uri(client: FlaskClient) -> None:
    import tontraeger_server.web as web_module

    mock_sonos = MagicMock()
    mock_sonos.get_current_track_uri.return_value = "x-sonosapi-radio:s25111"
    original = web_module.sonos
    web_module.sonos = mock_sonos

    resp = client.get("/now-playing")
    assert resp.status_code == 200
    assert resp.json == {"uri": "x-sonosapi-radio:s25111"}

    web_module.sonos = original


def test_now_playing_nothing_playing(client: FlaskClient) -> None:
    import tontraeger_server.web as web_module

    mock_sonos = MagicMock()
    mock_sonos.get_current_track_uri.return_value = None
    original = web_module.sonos
    web_module.sonos = mock_sonos

    resp = client.get("/now-playing")
    assert resp.status_code == 200
    assert resp.json == {"uri": None}

    web_module.sonos = original


def test_now_playing_error(client: FlaskClient) -> None:
    import tontraeger_server.web as web_module

    mock_sonos = MagicMock()
    mock_sonos.get_current_track_uri.side_effect = Exception("Speaker offline")
    original = web_module.sonos
    web_module.sonos = mock_sonos

    resp = client.get("/now-playing")
    assert resp.status_code == 200
    assert resp.json == {"uri": None}

    web_module.sonos = original


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
    assert resp.json["mappings"][0] == {"tag_uid": "aaa", "media_uri": "uri_a", "name": "Alpha", "shuffle": False}
    assert resp.json["mappings"][1] == {"tag_uid": "bbb", "media_uri": "uri_b", "name": "", "shuffle": False}


def test_add_mapping_with_shuffle(client: FlaskClient) -> None:
    resp = client.post("/mappings", data={"tag_uid": "333", "media_uri": "https://spotify.com/playlist", "name": "Radio", "shuffle": "on"})
    assert resp.status_code == 302

    resp = client.get("/api/mappings")
    assert resp.json["mappings"][0]["shuffle"] is True


def test_add_mapping_without_shuffle_defaults_false(client: FlaskClient) -> None:
    client.post("/mappings", data={"tag_uid": "444", "media_uri": "uri_d", "name": "Ordered"})

    resp = client.get("/api/mappings")
    assert resp.json["mappings"][0]["shuffle"] is False


def test_etag_changes_on_shuffle_toggle(client: FlaskClient) -> None:
    """Toggling shuffle on a mapping must invalidate the ETag."""
    client.post("/mappings", data={"tag_uid": "aaa", "media_uri": "uri_a", "name": ""})
    resp1 = client.get("/api/mappings")
    old_etag = resp1.headers["ETag"]

    # Re-add same mapping with shuffle=True (INSERT OR REPLACE)
    client.post("/mappings", data={"tag_uid": "aaa", "media_uri": "uri_a", "name": "", "shuffle": "on"})
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
    # Speaker picker
    assert 'x-model="selectedSpeaker"' in html
    # Unknown tags section
    assert "loadUnknownTags" in html
    assert "useTag" in html
    assert "/api/unknown-tags" in html
    assert "/api/speakers" in html


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
        mock_instance.get_current_track_uri.return_value = "x-radio:123"
        MockSonosAPI.return_value = mock_instance

        resp = client.get("/now-playing?speaker=Kitchen")
        assert resp.status_code == 200
        assert resp.json == {"uri": "x-radio:123"}
        MockSonosAPI.assert_called_once_with("Kitchen")


def test_now_playing_with_unknown_speaker(client: FlaskClient) -> None:
    with patch("tontraeger_server.web.SonosAPI", side_effect=Exception("not found")):
        resp = client.get("/now-playing?speaker=Nonexistent")
        assert resp.json == {"uri": None}


def test_now_playing_without_speaker_param_uses_default(client: FlaskClient) -> None:
    import tontraeger_server.web as web_module
    mock_sonos = MagicMock()
    mock_sonos.get_current_track_uri.return_value = "x-default:999"
    original = web_module.sonos
    web_module.sonos = mock_sonos

    resp = client.get("/now-playing")
    assert resp.json == {"uri": "x-default:999"}

    web_module.sonos = original
