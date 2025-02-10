#!/usr/bin/env python
# spotibox/play_playlist.py

import argparse
from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE
from spotify_api import SpotifyAPI

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start playback of a Spotify playlist on an active device (e.g. your iPhone)."
    )
    parser.add_argument(
        "playlist_uri",
        type=str,
        help="The Spotify playlist URI to play (e.g., spotify:playlist:YOUR_PLAYLIST_ID)"
    )
    args = parser.parse_args()

    spotify_api = SpotifyAPI(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE)
    try:
        spotify_api.start_playlist(args.playlist_uri)
        print("Playback started successfully.")
    except Exception as e:
        print(f"Error starting playback: {e}")

if __name__ == "__main__":
    main()
