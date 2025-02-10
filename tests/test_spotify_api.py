# tests/test_spotify_api.py

import pytest
from unittest.mock import patch, MagicMock
from spotibox.spotify_api import SpotifyAPI

@pytest.fixture
def spotify_api() -> SpotifyAPI:
    # Patch SpotifyOAuth to bypass the actual OAuth flow.
    with patch('spotibox.spotify_api.SpotifyOAuth') as mock_oauth:
        mock_oauth.return_value = MagicMock()
        # Patch spotipy.Spotify so we can control its behavior.
        with patch('spotibox.spotify_api.spotipy.Spotify') as mock_sp:
            instance = mock_sp.return_value
            instance.devices.return_value = {
                'devices': [
                    {'name': 'iPhone', 'type': 'Smartphone', 'id': 'device_id_1'},
                    {'name': 'Laptop', 'type': 'Computer', 'id': 'device_id_2'}
                ]
            }
            yield SpotifyAPI('client_id', 'client_secret', 'redirect_uri', 'scope')

def test_get_devices(spotify_api: SpotifyAPI) -> None:
    devices = spotify_api.get_devices()
    assert devices is not None
    assert len(devices) == 2
    assert devices[0]['name'] == 'iPhone'
    assert devices[1]['name'] == 'Laptop'

def test_start_playlist(spotify_api: SpotifyAPI) -> None:
    # Given a sample playlist URI.
    playlist_uri = "spotify:playlist:TEST_URI"
    # Patch the start_playback method on the Spotify client.
    spotify_api.sp.start_playback = MagicMock()
    
    # Invoke the function.
    spotify_api.start_playlist(playlist_uri)
    
    # Verify that start_playback was called with the iPhone device id and correct playlist URI.
    spotify_api.sp.start_playback.assert_called_once_with(
        device_id='device_id_1',
        context_uri=playlist_uri
    )

def test_stop_playback(spotify_api: SpotifyAPI) -> None:
    # Patch the pause_playback method on the Spotify client.
    spotify_api.sp.pause_playback = MagicMock()
    
    # Call the new stop_playback method.
    spotify_api.stop_playback()
    
    # Verify that pause_playback was called exactly once with the expected iPhone device ID.
    spotify_api.sp.pause_playback.assert_called_once_with(device_id='device_id_1')

