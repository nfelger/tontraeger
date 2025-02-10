#!/usr/bin/env python
import argparse
from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE
from spotify_api import SpotifyAPI

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stop playback on an active device (e.g. your iPhone)."
    )
    # No additional arguments are needed.
    args = parser.parse_args()

    spotify_api = SpotifyAPI(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE)
    try:
        spotify_api.stop_playback()
        print("Playback stopped successfully.")
    except Exception as e:
        print(f"Error stopping playback: {e}")

if __name__ == "__main__":
    main()
