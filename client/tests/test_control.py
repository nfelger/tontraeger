import pytest
import asyncio
from unittest.mock import MagicMock
from typing import Optional
from tontraeger_client.cache import MappingCache
from tontraeger_client.control import PlaybackController, STOP_COMMAND, main_loop


class DummySonosAPI:
    def __init__(self) -> None:
        self.played_uri: Optional[str] = None
        self.stopped: bool = False

    def play_uri(self, uri: str) -> None:
        self.played_uri = uri

    def stop_playback(self) -> None:
        self.stopped = True


@pytest.fixture
def cache(tmp_path):
    return MappingCache(str(tmp_path / "mappings.json"))


def test_handle_tag_plays_uri(cache) -> None:
    cache.update([{"tag_uid": "tag1", "media_uri": "x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0", "name": ""}])
    sonos_api = DummySonosAPI()
    controller = PlaybackController(sonos_api, cache)

    controller.handle_tag("tag1")
    assert sonos_api.played_uri == "x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0"
    assert not sonos_api.stopped


def test_handle_tag_stops_playback(cache) -> None:
    cache.update([{"tag_uid": "tag2", "media_uri": STOP_COMMAND, "name": ""}])
    sonos_api = DummySonosAPI()
    controller = PlaybackController(sonos_api, cache)

    controller.handle_tag("tag2")
    assert sonos_api.stopped
    assert sonos_api.played_uri is None


def test_handle_tag_unknown_does_not_raise(cache) -> None:
    """Unknown tags no longer raise — they return silently."""
    sonos_api = DummySonosAPI()
    controller = PlaybackController(sonos_api, cache)

    # Should not raise
    controller.handle_tag("missing")
    assert sonos_api.played_uri is None
    assert not sonos_api.stopped


def test_handle_tag_unknown_reports_to_sync(cache) -> None:
    """When sync is provided, unknown tags are reported to the server."""
    sonos_api = DummySonosAPI()
    mock_sync = MagicMock()
    controller = PlaybackController(sonos_api, cache, sync=mock_sync)

    controller.handle_tag("unknown_tag")
    mock_sync.report_unknown_tag.assert_called_once_with("unknown_tag")


def test_handle_tag_unknown_without_sync(cache) -> None:
    """Without sync, unknown tags are silently ignored (no crash)."""
    sonos_api = DummySonosAPI()
    controller = PlaybackController(sonos_api, cache, sync=None)

    # Should not raise
    controller.handle_tag("unknown_tag")


class FakeRFIDReader:
    def __init__(self, tags):
        self.tags = tags
        self.index = 0

    def read_tag(self) -> str:
        if self.index < len(self.tags):
            tag = self.tags[self.index]
            self.index += 1
            return tag
        return None

    def cleanup(self) -> None:
        pass


class FakePlaybackController:
    def __init__(self):
        self.handled_tags = []

    def handle_tag(self, tag: str) -> None:
        self.handled_tags.append(tag)


@pytest.mark.asyncio
async def test_main_loop_no_duplicate():
    tags = ['123', '456']
    reader = FakeRFIDReader(tags)
    controller = FakePlaybackController()

    await main_loop(reader, controller, max_iterations=2)
    await asyncio.sleep(0.1)
    assert controller.handled_tags == ['123', '456']


@pytest.mark.asyncio
async def test_main_loop_debounce_duplicate():
    tags = ['123', '123', '456']
    reader = FakeRFIDReader(tags)
    controller = FakePlaybackController()

    await main_loop(reader, controller, max_iterations=2)
    await asyncio.sleep(0.1)
    assert controller.handled_tags == ['123', '456']
