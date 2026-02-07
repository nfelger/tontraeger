from soco import SoCo
from soco.plugins.sharelink import ShareLinkPlugin
from typing import Optional
import soco


class SonosAPI:
    def __init__(self, speaker_name: str) -> None:
        """
        Initialize with target speaker name (e.g., 'Living Room').

        Args:
            speaker_name: Name of the Sonos speaker to control

        Raises:
            Exception: If no speakers found or speaker name doesn't match
        """
        self.speaker_name = speaker_name
        self._speaker: Optional[SoCo] = None
        self._discover_speaker()

    def _discover_speaker(self) -> None:
        """
        Find speaker by name from soco.discover().

        Raises:
            Exception: If no speakers found on network or speaker name not found
        """
        speakers = soco.discover()
        if not speakers:
            raise Exception("No Sonos speakers found on network")

        self._speaker = next(
            (s for s in speakers if s.player_name == self.speaker_name), None
        )
        if not self._speaker:
            available = ", ".join(s.player_name for s in speakers)
            raise Exception(
                f"Speaker '{self.speaker_name}' not found. Available speakers: {available}"
            )

    def start_playlist(self, share_url: str) -> None:
        """
        Start playback using Spotify share URL.
        Uses ShareLinkPlugin to avoid UPnP Error 804.

        Args:
            share_url: Full Spotify share URL (e.g., https://open.spotify.com/playlist/ID)
        """
        if not self._speaker:
            raise Exception("Speaker not initialized")

        self._speaker.clear_queue()
        share_link = ShareLinkPlugin(self._speaker)
        share_link.add_share_link_to_queue(share_url)
        self._speaker.play_from_queue(0)

    def stop_playback(self) -> None:
        """Pause playback on speaker"""
        if not self._speaker:
            raise Exception("Speaker not initialized")

        self._speaker.pause()
