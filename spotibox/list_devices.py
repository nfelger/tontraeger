# spotibox/list_devices.py

from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE
from spotify_api import SpotifyAPI

def main() -> None:
    spotify_api = SpotifyAPI(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE)
    devices = spotify_api.get_devices()

    print("Available devices:")
    if devices:
        for device in devices:
            device_name = device.get('name', 'Unknown')
            device_type = device.get('type', 'Unknown')
            device_id = device.get('id', 'Unknown')
            print(f"Name: {device_name} | Type: {device_type} | ID: {device_id}")
            if "iPhone" in device_name:
                print("Success: Your iPhone is available in the device list!")
    else:
        print("No devices found. Make sure your Spotify app is active on a device.")

if __name__ == '__main__':
    main()
