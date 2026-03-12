import asyncio
import logging
import os
import signal

from tontraeger_client.cache import MappingCache
from tontraeger_client.config import (
    CACHE_PATH,
    NFC_DAEMON_PATH,
    SONOS_SPEAKER_NAME,
    TONTRAEGER_SERVER,
)
from tontraeger_client.control import PlaybackController, nfc_reader
from tontraeger_client.sonos_api import SonosAPI
from tontraeger_client.sync import MappingSync

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Starting tontraeger client")
    logger.info("Server: %s", TONTRAEGER_SERVER)
    logger.info("Speaker: %s", SONOS_SPEAKER_NAME)
    logger.info("Cache: %s", CACHE_PATH)
    logger.info("NFC daemon: %s", NFC_DAEMON_PATH)

    cache = MappingCache(CACHE_PATH)
    sonos_api = SonosAPI(SONOS_SPEAKER_NAME)
    sync = MappingSync(TONTRAEGER_SERVER, cache)
    controller = PlaybackController(sonos_api, cache, sync)

    # systemd sends SIGTERM to stop services. Cancel all tasks so the NFC daemon
    # child process gets cleaned up (via the finally block in nfc_reader).
    loop = asyncio.get_running_loop()

    def _on_sigterm() -> None:
        logger.info("SIGTERM received, shutting down")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    loop.add_signal_handler(signal.SIGTERM, _on_sigterm)

    # Try to fetch mappings from the server before we start listening for tags.
    # If the server is down, that's fine — we'll use whatever's in the cache.
    try:
        await loop.run_in_executor(None, sync.poll)
    except Exception as e:
        logger.warning("Initial sync failed: %s", e)

    # Start polling for mapping updates and looking for the Sonos speaker.
    sync_task = asyncio.create_task(sync.run())
    discover_task = asyncio.create_task(sonos_api.discover())

    try:
        await nfc_reader(controller, NFC_DAEMON_PATH)
    except asyncio.CancelledError:
        logger.info("Shutting down")
    finally:
        sync_task.cancel()
        discover_task.cancel()
        # Suppress errors from cancelled background tasks.
        for task in (sync_task, discover_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


def run() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
    logger.info("tontraeger client stopped")
    # Force-exit. Sonos and HTTP calls run in background threads that may
    # still be blocked on network I/O. Without this, the process hangs.
    os._exit(0)


if __name__ == "__main__":
    run()
