# spotibox/control.py

import asyncio
import argparse
import time
from typing import Optional

from config import CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE
from spotify_api import SpotifyAPI
from playlist_mapper import PlaylistMapper
from rfid_reader import RFIDReader

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
        playlist_uri = self.mapper.get_playlist_uri(tag_uid)
        if playlist_uri is None:
            raise Exception(f"No mapping found for tag: {tag_uid}")
        if playlist_uri.upper() == STOP_COMMAND:
            self.spotify_api.stop_playback()
        else:
            self.spotify_api.start_playlist(playlist_uri)

async def process_tag(tag: str, controller: PlaybackController) -> None:
    """
    Asynchronously processes a tag by invoking the controller.
    Errors are caught and logged.
    """
    try:
        controller.handle_tag(tag)
        print(f"Processed tag {tag} successfully.")
    except Exception as e:
        print(f"Error processing tag {tag}: {e}")

async def main_loop(reader: RFIDReader, controller: PlaybackController, max_iterations: Optional[int] = None) -> None:
    """
    Continuously listens for RFID tags. Optionally stops after max_iterations (useful for testing).
    A debouncing mechanism is implemented to ignore duplicate reads of the same tag within a short interval.
    The blocking reader.read_tag() call is run in an executor so the event loop remains responsive.
    """
    loop = asyncio.get_running_loop()
    iteration = 0
    last_tag = None
    last_tag_time = 0.0
    DEBOUNCE_INTERVAL = 5.0  # seconds

    try:
        while True:
            tag = await loop.run_in_executor(None, reader.read_tag)
            now = time.time()
            if tag == last_tag and (now - last_tag_time) < DEBOUNCE_INTERVAL:
                print(f"Ignoring duplicate tag {tag} (debounce active)")
                continue

            last_tag = tag
            last_tag_time = now

            # Process the new tag concurrently.
            asyncio.create_task(process_tag(tag, controller))
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break
    except KeyboardInterrupt:
        print("Shutting down.")
    finally:
        reader.cleanup()

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuous RFID-controlled Spotify playback."
    )
    parser.parse_args()

    spotify_api = SpotifyAPI(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, SCOPE)
    mapper = PlaylistMapper()
    controller = PlaybackController(spotify_api, mapper)
    reader = RFIDReader()

    # Run the asynchronous main loop.
    asyncio.run(main_loop(reader, controller))

if __name__ == "__main__":
    main()
