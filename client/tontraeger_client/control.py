import asyncio
import logging
import time
from typing import Optional, Protocol

from tontraeger_client.cache import MappingCache
from tontraeger_client.sonos_api import SonosAPI
from tontraeger_client.sync import MappingSync

logger = logging.getLogger(__name__)


class TagReader(Protocol):
    def read_tag(self) -> str: ...
    def cleanup(self) -> None: ...

# Constant representing the stop command.
STOP_COMMAND: str = "STOP"

class PlaybackController:
    def __init__(
        self,
        sonos_api: SonosAPI,
        cache: MappingCache,
        sync: Optional[MappingSync] = None,
    ) -> None:
        self.sonos_api = sonos_api
        self.cache = cache
        self.sync = sync

    def handle_tag(self, tag_uid: str) -> None:
        """Given a tag UID, look up the URI in the local cache.

        - If found and URI is STOP: stop playback.
        - If found: play the URI.
        - If not found: log and report to server as unknown tag.
        """
        uri = self.cache.get_uri(tag_uid)
        if uri is None:
            logger.info("Unknown tag: %s", tag_uid)
            if self.sync is not None:
                self.sync.report_unknown_tag(tag_uid)
            return
        if uri.upper() == STOP_COMMAND:
            self.sonos_api.stop_playback()
        else:
            self.sonos_api.play_uri(uri)

async def process_tag(tag: str, controller: PlaybackController) -> None:
    """Asynchronously processes a tag by invoking the controller.
    Errors are caught and logged.
    """
    try:
        controller.handle_tag(tag)
        logger.info("Processed tag %s successfully.", tag)
    except Exception as e:
        logger.error("Error processing tag %s: %s", tag, e)

async def main_loop(reader: TagReader, controller: PlaybackController, max_iterations: Optional[int] = None) -> None:
    """Continuously listens for RFID tags. Optionally stops after max_iterations (useful for testing).
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
                logger.debug("Ignoring duplicate tag %s (debounce active)", tag)
                continue

            last_tag = tag
            last_tag_time = now

            asyncio.create_task(process_tag(tag, controller))
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break
    except KeyboardInterrupt:
        logger.info("Shutting down.")
    finally:
        reader.cleanup()
