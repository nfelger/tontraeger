import pytest
import asyncio
from typing import Optional
from spotibox.control import PlaybackController, STOP_COMMAND, main_loop

# Dummy implementations for testing purposes.

class DummySonosAPI:
    def __init__(self) -> None:
        self.played_uri: Optional[str] = None
        self.stopped: bool = False

    def play_uri(self, uri: str) -> None:
        self.played_uri = uri

    def stop_playback(self) -> None:
        self.stopped = True

class DummyTagMapper:
    def __init__(self, mapping: dict) -> None:
        self.mapping = mapping

    def get_uri(self, tag_uid: str) -> Optional[str]:
        return self.mapping.get(tag_uid)

def test_handle_tag_plays_uri() -> None:
    # Given a tag that maps to a media URI.
    mapping = {"tag1": "x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0"}
    mapper = DummyTagMapper(mapping)
    sonos_api = DummySonosAPI()
    controller = PlaybackController(sonos_api, mapper)

    controller.handle_tag("tag1")
    assert sonos_api.played_uri == "x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0"
    assert not sonos_api.stopped

def test_handle_tag_stops_playback() -> None:
    # Given a tag that maps to the special stop command.
    mapping = {"tag2": STOP_COMMAND}
    mapper = DummyTagMapper(mapping)
    sonos_api = DummySonosAPI()
    controller = PlaybackController(sonos_api, mapper)

    controller.handle_tag("tag2")
    assert sonos_api.stopped
    assert sonos_api.played_uri is None

def test_handle_tag_no_mapping() -> None:
    # When a tag does not exist in the mapping, an exception is raised.
    mapping = {"tag3": "x-sonosapi-radio:s12345?sid=254&flags=8224&sn=0"}
    mapper = DummyTagMapper(mapping)
    sonos_api = DummySonosAPI()
    controller = PlaybackController(sonos_api, mapper)

    with pytest.raises(Exception, match="No mapping found for tag: missing"):
        controller.handle_tag("missing")

class FakeRFIDReader:
    def __init__(self, tags):
        self.tags = tags
        self.index = 0

    def read_tag(self) -> str:
        """
        Returns the next tag from the list, or None if exhausted.
        """
        # Simulate fast successive reads.
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
    # Test with two different tags: both should be processed.
    tags = ['123', '456']
    reader = FakeRFIDReader(tags)
    controller = FakePlaybackController()

    # Process exactly 2 distinct tag events.
    await main_loop(reader, controller, max_iterations=2)

    # Allow any spawned tasks time to complete.
    await asyncio.sleep(0.1)
    assert controller.handled_tags == ['123', '456']

@pytest.mark.asyncio
async def test_main_loop_debounce_duplicate():
    # Test with a duplicate tag in rapid succession.
    tags = ['123', '123', '456']
    reader = FakeRFIDReader(tags)
    controller = FakePlaybackController()

    # Even though there are 3 reads, the duplicate '123' should be debounced.
    # We set max_iterations=2 so that only 2 distinct tags are processed.
    await main_loop(reader, controller, max_iterations=2)

    # Allow any spawned tasks time to complete.
    await asyncio.sleep(0.1)
    # The expected behavior: first '123' is processed, second '123' is ignored, then '456' is processed.
    assert controller.handled_tags == ['123', '456']
