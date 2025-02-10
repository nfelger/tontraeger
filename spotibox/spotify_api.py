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
        """Fetches available devices as a list of dictionaries."""
        devices_info: Dict[str, Any] = self.sp.devices()
        return devices_info.get('devices', None)

    def start_playlist(self, playlist_uri: str) -> None:
        """
        Starts playback of the given playlist URI on an active device whose name contains 'iPhone'.
        """
        devices: Optional[List[Dict[str, Any]]] = self.get_devices()
        if not devices:
            raise Exception("No active devices found.")
        
        target_device_id: Optional[str] = None
        for device in devices:
            if "iPhone" in device.get("name", ""):
                target_device_id = device.get("id")
                break
        
        if not target_device_id:
            raise Exception("No active iPhone device found.")
        
        self.sp.start_playback(device_id=target_device_id, context_uri=playlist_uri)

    def stop_playback(self) -> None:
        """
        Stops playback on an active device whose name contains 'iPhone'.
        """
        devices: Optional[List[Dict[str, Any]]] = self.get_devices()
        if not devices:
            raise Exception("No active devices found.")
        
        target_device_id: Optional[str] = None
        for device in devices:
            if "iPhone" in device.get("name", ""):
                target_device_id = device.get("id")
                break
        
        if not target_device_id:
            raise Exception("No active iPhone device found.")
        
        self.sp.pause_playback(device_id=target_device_id)
