import asyncio
import logging

import soco
from soco import SoCo
from soco.plugins.sharelink import ShareLinkPlugin

logger = logging.getLogger(__name__)


class SonosAPI:
    def __init__(self, speaker_name: str) -> None:
        """Initialize with target speaker name. Discovery happens lazily."""
        self.speaker_name = speaker_name
        self._speaker: SoCo | None = None

    def _find_speaker(self) -> SoCo:
        """Search the network for the speaker. Raises if not found."""
        speakers = soco.discover()
        if not speakers:
            raise RuntimeError("No Sonos speakers found on network")

        speaker = next((s for s in speakers if s.player_name == self.speaker_name), None)
        if not speaker:
            available = ", ".join(s.player_name for s in speakers)
            raise RuntimeError(
                f"Speaker '{self.speaker_name}' not found. Available: {available}"
            )
        return speaker

    def _do_play(self, uri: str) -> None:
        """Clear queue, add URI, and start playing. Blocking (network I/O)."""
        if self._speaker is None:
            raise RuntimeError("Speaker not initialized")
        self._speaker.clear_queue()
        if uri.startswith("https://"):
            ShareLinkPlugin(self._speaker).add_share_link_to_queue(uri)
        else:
            self._speaker.add_uri_to_queue(uri)
        self._speaker.play_from_queue(0)

    async def discover(self) -> None:
        """Keep searching for the speaker until found. Retries every 5s."""
        loop = asyncio.get_running_loop()
        while self._speaker is None:
            try:
                self._speaker = await loop.run_in_executor(None, self._find_speaker)
                logger.info("Discovered speaker: %s", self.speaker_name)
            except Exception as e:
                logger.warning("Speaker discovery failed: %s — retrying in 5s", e)
                await asyncio.sleep(5)

    async def play_uri(self, uri: str) -> None:
        """Play a URI. Finds the speaker first if needed.

        On error, forgets the speaker so the next call rediscovers it.
        """
        if self._speaker is None:
            await self.discover()

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._do_play, uri)
        except Exception as e:
            logger.error("play_uri failed: %s — clearing speaker for rediscovery", e)
            self._speaker = None
            raise

    async def stop_playback(self) -> None:
        """Pause playback. Does nothing if no speaker has been found yet."""
        if self._speaker is None:
            return

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._speaker.pause)
        except Exception as e:
            logger.error("stop_playback failed: %s — clearing speaker for rediscovery", e)
            self._speaker = None
