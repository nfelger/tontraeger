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
        self._pending_discover: asyncio.Task[None] | None = None

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

    def _do_play(self, uri: str, shuffle: bool = False) -> None:
        """Clear queue, set play mode, add URI, and start playing. Blocking (network I/O)."""
        if self._speaker is None:
            raise RuntimeError("Speaker not initialized")
        # Playback commands must go to the group coordinator. If the speaker
        # is a slave in a group, SoCo raises SoCoSlaveException otherwise.
        coordinator = self._speaker.group.coordinator
        coordinator.clear_queue()
        coordinator.play_mode = "SHUFFLE" if shuffle else "NORMAL"
        if uri.startswith("https://"):
            ShareLinkPlugin(coordinator).add_share_link_to_queue(uri)
        else:
            coordinator.add_uri_to_queue(uri)
        coordinator.play_from_queue(0)

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

    async def play_uri(self, uri: str, shuffle: bool = False) -> None:
        """Play a URI. Finds the speaker first if needed.

        On error, forgets the speaker so the next call rediscovers it.
        """
        if self._speaker is None:
            await self.discover()

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, lambda: self._do_play(uri, shuffle))
        except Exception as e:
            logger.error("play_uri failed: %s — clearing speaker for rediscovery", e)
            self._speaker = None
            # Immediately kick off rediscovery so stop_playback() remains functional
            # for any REMOVED event that arrives before the next PRESENT.
            # Store reference to prevent GC before the task completes.
            self._pending_discover = asyncio.create_task(self.discover())
            raise

    async def stop_playback(self) -> None:
        """Pause playback. Does nothing if no speaker has been found yet."""
        if self._speaker is None:
            return

        loop = asyncio.get_running_loop()
        try:
            coordinator = self._speaker.group.coordinator
            await loop.run_in_executor(None, coordinator.pause)
        except Exception as e:
            logger.error("stop_playback failed: %s", e)
            # Do NOT clear _speaker. A transport error (already stopped, transitioning)
            # does not mean the speaker is unreachable. Clearing it here causes the next
            # REMOVED event to silently short-circuit on `if self._speaker is None: return`.
