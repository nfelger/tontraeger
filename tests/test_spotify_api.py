import pytest
from unittest.mock import patch, MagicMock
from spotibox.spotify_api import SpotifyAPI

@pytest.fixture
def spotify_api() -> SpotifyAPI:
    # Patch SpotifyOAuth to prevent triggering browser-based authentication.
    with patch('spotibox.spotify_api.SpotifyOAuth') as mock_oauth:
        dummy_oauth = MagicMock()
        mock_oauth.return_value = dummy_oauth
        # Patch the Spotify client so that no real HTTP call is made.
        with patch('spotibox.spotify_api.spotipy.Spotify') as mock_sp:
            instance = mock_sp.return_value
            instance.devices.return_value = {
                'devices': [
                    {'name': 'iPhone', 'type': 'Smartphone', 'id': 'device_id_1'},
                    {'name': 'Laptop', 'type': 'Computer', 'id': 'device_id_2'}
                ]
            }
            # Now that the patches are active, create the SpotifyAPI instance.
            return SpotifyAPI('client_id', 'client_secret', 'redirect_uri', 'scope')

def test_get_devices(spotify_api: SpotifyAPI) -> None:
    devices = spotify_api.get_devices()
    assert devices is not None
    assert len(devices) == 2
    assert devices[0]['name'] == 'iPhone'
    assert devices[1]['name'] == 'Laptop'
