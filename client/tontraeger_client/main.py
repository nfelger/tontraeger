import asyncio
import logging
import os
import signal

from tontraeger_client.cache import MappingCache
from tontraeger_client.config import CACHE_PATH, SONOS_SPEAKER_NAME, TONTRAEGER_SERVER
from tontraeger_client.control import PlaybackController, main_loop
from tontraeger_client.sonos_api import SonosAPI
from tontraeger_client.sync import MappingSync

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Starting tontraeger client")
    logger.info("Server: %s", TONTRAEGER_SERVER)
    logger.info("Speaker: %s", SONOS_SPEAKER_NAME)
    logger.info("Cache: %s", CACHE_PATH)

    # Import RFIDReader here to avoid importing RPi.GPIO on non-Pi machines
    from tontraeger_client.rfid_reader import RFIDReader

    cache = MappingCache(CACHE_PATH)
    sonos_api = SonosAPI(SONOS_SPEAKER_NAME)
    sync = MappingSync(TONTRAEGER_SERVER, cache)
    controller = PlaybackController(sonos_api, cache, sync)
    reader = RFIDReader()

    # Initial sync: fetch mappings from server before starting the main loop
    logger.info("Performing initial sync...")
    sync.poll()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown() -> None:
        logger.info("Shutdown requested")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    loop.add_signal_handler(signal.SIGINT, shutdown)
    loop.add_signal_handler(signal.SIGTERM, shutdown)

    async def run() -> None:
        sync_task = asyncio.get_running_loop().run_in_executor(None, sync.run)
        rfid_task = asyncio.ensure_future(main_loop(reader, controller))

        try:
            await asyncio.gather(sync_task, rfid_task)
        except asyncio.CancelledError:
            logger.info("Tasks cancelled, shutting down")

    try:
        loop.run_until_complete(run())
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        reader.cleanup()
        loop.close()
        logger.info("tontraeger client stopped")
        # The RFID reader thread (reader.read_tag) may be stuck in a blocking
        # SPI call that cannot be interrupted.  Since ThreadPoolExecutor uses
        # non-daemon threads, the process would hang forever waiting for that
        # thread.  Force-exit after all cleanup is done.
        os._exit(0)


if __name__ == "__main__":
    main()
