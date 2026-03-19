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

    def play_uri(self, uri: str) -> None:
        """
        Clear the queue, add the URI, and play from the start.

        Works with both directly-playable URIs (radio streams, tracks)
        and container URIs (albums, playlists).

        Args:
            uri: A SoCo-compatible media URI
        """
        if not self._speaker:
            raise Exception("Speaker not initialized")

        # Playback commands must go to the group coordinator. If the speaker
        # is a slave in a group, SoCo raises SoCoSlaveException otherwise.
        coordinator = self._speaker.group.coordinator
        coordinator.clear_queue()
        if uri.startswith("https://"):
            ShareLinkPlugin(coordinator).add_share_link_to_queue(uri)
        else:
            coordinator.add_uri_to_queue(uri)
        coordinator.play_from_queue(0)

    def get_current_track_info(self) -> dict[str, Optional[str]]:
        """Return URI of the currently playing track."""
        if not self._speaker:
            raise Exception("Speaker not initialized")

        coordinator = self._speaker.group.coordinator
        info = coordinator.get_current_track_info()
        uri = info.get("uri", "")
        return {"uri": uri if uri else None}

    def stop_playback(self) -> None:
        """Pause playback on speaker."""
        if not self._speaker:
            raise Exception("Speaker not initialized")

        self._speaker.group.coordinator.pause()
