import argparse
from typing import Optional
from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE
from spotify_api import SpotifyAPI
from playlist_mapper import PlaylistMapper

# Constant representing the stop command.
STOP_COMMAND: str = "STOP"

class PlaybackController:
    def __init__(self, spotify_api: SpotifyAPI, mapper: PlaylistMapper) -> None:
        """
        Initializes the controller with a SpotifyAPI instance and a PlaylistMapper.
        """
        self.spotify_api = spotify_api
        self.mapper = mapper

    def handle_tag(self, tag_uid: str) -> None:
        """
        Given a tag UID, retrieves the associated playlist URI from the mapper.
        - If the returned URI matches the special STOP_COMMAND, it stops playback.
        - Otherwise, it starts playback of the given playlist.
        Raises:
            Exception: if no mapping exists for the tag.
        """
        playlist_uri: Optional[str] = self.mapper.get_playlist_uri(tag_uid)
        if playlist_uri is None:
            raise Exception(f"No mapping found for tag: {tag_uid}")
        if playlist_uri.upper() == STOP_COMMAND:
            self.spotify_api.stop_playback()
        else:
            self.spotify_api.start_playlist(playlist_uri)

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Control Spotify playback based on a tag ID."
    )
    parser.add_argument(
        "tag_id",
        type=str,
        help="The tag ID to process (maps to a playlist URI or a STOP command)."
    )
    args = parser.parse_args()

    # Create a SpotifyAPI instance using config values.
    spotify_api = SpotifyAPI(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE)
    # Create a PlaylistMapper instance (using default DB: playlists.db).
    mapper = PlaylistMapper()
    # Create the controller.
    controller = PlaybackController(spotify_api, mapper)

    try:
        controller.handle_tag(args.tag_id)
        print(f"Playback action for tag '{args.tag_id}' executed successfully.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
