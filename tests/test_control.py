# tests/test_control.py

import pytest
from typing import Optional
from spotibox.control import PlaybackController, STOP_COMMAND

# Dummy implementations for testing purposes.

class DummySpotifyAPI:
    def __init__(self) -> None:
        self.started_playlist: Optional[str] = None
        self.stopped: bool = False

    def start_playlist(self, playlist_uri: str) -> None:
        self.started_playlist = playlist_uri

    def stop_playback(self) -> None:
        self.stopped = True

class DummyPlaylistMapper:
    def __init__(self, mapping: dict) -> None:
        self.mapping = mapping

    def get_playlist_uri(self, tag_uid: str) -> Optional[str]:
        return self.mapping.get(tag_uid)

def test_handle_tag_starts_playlist() -> None:
    # Given a tag that maps to a normal playlist URI.
    mapping = {"tag1": "spotify:playlist:TEST_URI"}
    mapper = DummyPlaylistMapper(mapping)
    spotify_api = DummySpotifyAPI()
    controller = PlaybackController(spotify_api, mapper)

    controller.handle_tag("tag1")
    assert spotify_api.started_playlist == "spotify:playlist:TEST_URI"
    assert not spotify_api.stopped

def test_handle_tag_stops_playback() -> None:
    # Given a tag that maps to the special stop command.
    mapping = {"tag2": STOP_COMMAND}
    mapper = DummyPlaylistMapper(mapping)
    spotify_api = DummySpotifyAPI()
    controller = PlaybackController(spotify_api, mapper)

    controller.handle_tag("tag2")
    assert spotify_api.stopped
    assert spotify_api.started_playlist is None

def test_handle_tag_no_mapping() -> None:
    # When a tag does not exist in the mapping, an exception is raised.
    mapping = {"tag3": "spotify:playlist:TEST_URI"}
    mapper = DummyPlaylistMapper(mapping)
    spotify_api = DummySpotifyAPI()
    controller = PlaybackController(spotify_api, mapper)

    with pytest.raises(Exception, match="No mapping found for tag: missing"):
        controller.handle_tag("missing")
