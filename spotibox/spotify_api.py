# spotibox/spotify_api.py

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from typing import Any, Dict, List, Optional

class SpotifyAPI:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, scope: str) -> None:
        self.sp = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=redirect_uri,
                scope=scope
            )
        )

    def get_devices(self) -> Optional[List[Dict[str, Any]]]:
        devices_info = self.sp.devices()
        return devices_info.get('devices', None)
