import asyncio
import logging
import time

import requests
import soco
import soco.config
from soco import SoCo
from soco.exceptions import SoCoUPnPException
from soco.plugins.sharelink import ShareLinkPlugin

logger = logging.getLogger(__name__)

# SoCo defaults to 20s, which is far too generous for LAN state-changes on a
# Sonos box. Failures (e.g. speaker stalling on Spotify cloud) take 20s to
# surface, hammering the backoff in sonos_api before it can do its job.
soco.config.REQUEST_TIMEOUT = 5.0

# Backoff after consecutive play_uri failures. Index = consecutive_failures - 1.
# First failure has no penalty so a one-off glitch doesn't block the next tap.
_BACKOFF_SCHEDULE_S = (0, 2, 5, 15, 30)

# Errors where the speaker is reachable but rejecting or stalling — usually an
# upstream issue (e.g. Spotify outage), not a stale reference. Rediscovery would
# just hand back another SoCo pointing at the same misbehaving box.
_SPEAKER_REACHABLE_ERRORS = (requests.ReadTimeout, SoCoUPnPException)


class SonosAPI:
    def __init__(self, speaker_name: str) -> None:
        """Initialize with target speaker name. Discovery happens lazily."""
        self.speaker_name = speaker_name
        self._speaker: SoCo | None = None
        self._pending_discover: asyncio.Task[None] | None = None
        self._consecutive_failures = 0
        self._next_attempt_at = 0.0

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
        # play_from_queue internally calls play(), but Sonos can discard it when the
        # device is in TRANSITIONING state (e.g. after clearing the queue mid-play).
        # An explicit play() is a no-op if already playing and fixes the race.
        coordinator.play()

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

        Honours a backoff window after recent failures and only forgets the
        speaker for errors that suggest the cached reference is actually stale.
        """
        now = time.monotonic()
        if now < self._next_attempt_at:
            raise RuntimeError(
                f"Sonos in backoff after {self._consecutive_failures} failures "
                f"({self._next_attempt_at - now:.1f}s remaining)"
            )

        if self._speaker is None:
            await self.discover()

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, lambda: self._do_play(uri, shuffle))
        except _SPEAKER_REACHABLE_ERRORS as e:
            self._record_failure()
            logger.error("play_uri failed (speaker reachable, upstream issue?): %s", e)
            raise
        except Exception as e:
            self._record_failure()
            logger.error("play_uri failed: %s — clearing speaker for rediscovery", e)
            self._speaker = None
            # Immediately kick off rediscovery so stop_playback() remains functional
            # for any REMOVED event that arrives before the next PRESENT.
            # Store reference to prevent GC before the task completes.
            if self._pending_discover and not self._pending_discover.done():
                self._pending_discover.cancel()
            self._pending_discover = asyncio.create_task(self.discover())
            raise
        else:
            self._consecutive_failures = 0
            self._next_attempt_at = 0.0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        idx = min(self._consecutive_failures - 1, len(_BACKOFF_SCHEDULE_S) - 1)
        self._next_attempt_at = time.monotonic() + _BACKOFF_SCHEDULE_S[idx]

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
