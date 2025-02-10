import spotipy
from spotipy.oauth2 import SpotifyOAuth
from typing import Any, Dict, List

def main() -> None:
    client_id: str = 'a7936aae68834cd7984533b8c13ed851'
    client_secret: str = 'a6e7a8fcfb2946dca81c556c60bd754e'
    redirect_uri: str = 'http://localhost:8888/callback'
    scope: str = 'user-read-playback-state'

    # Authenticate with Spotify using OAuth.
    sp: spotipy.Spotify = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=scope
        )
    )

    # Fetch available devices; the API returns a dictionary.
    devices_info: Dict[str, Any] = sp.devices()

    print("Available devices:")
    if devices_info and devices_info.get('devices'):
        # 'devices' is expected to be a list of dictionaries.
        devices: List[Dict[str, Any]] = devices_info['devices']
        for device in devices:
            device_name: str = device.get('name', 'Unknown')
            device_type: str = device.get('type', 'Unknown')
            device_id: str = device.get('id', 'Unknown')
            print(f"Name: {device_name} | Type: {device_type} | ID: {device_id}")
            if "iPhone" in device_name:
                print("Success: Your iPhone is available in the device list!")
    else:
        print("No devices found. Make sure your Spotify app is active on a device.")

if __name__ == '__main__':
    main()
