import os
import tempfile
from unittest.mock import MagicMock

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


def test_now_playing_button_wired_correctly(client: FlaskClient) -> None:
    """Verify the template wires the button, input, and fetch script together."""
    html = client.get("/").data.decode()
    # Button exists and calls the JS function
    assert 'id="now-playing-btn"' in html
    assert 'onclick="fetchNowPlaying()"' in html
    # JS targets the correct input element ID
    assert "getElementById('media_uri')" in html
    # JS fetches the right endpoint
    assert "/now-playing" in html
