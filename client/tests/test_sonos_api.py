import pytest

from tontraeger_client.sonos_api import SonosAPI


async def _instant_sleep(_seconds: float) -> None:
    """Replacement for asyncio.sleep that returns immediately."""


class _FakeGroup:
    """Fake Sonos group where the speaker is its own coordinator."""

    def __init__(self, coordinator: "FakeSoCo") -> None:
        self.coordinator = coordinator


class FakeSoCo:
    """Fake Sonos speaker that records what was played."""

    def __init__(self, player_name: str = "Living Room") -> None:
        self.player_name = player_name
        self.queue: list[str] = []
        self.playing_from: int | None = None
        self.paused = False
        self.share_links: list[str] = []
        self.group = _FakeGroup(self)

    def clear_queue(self) -> None:
        self.queue.clear()
        self.share_links.clear()

    def add_uri_to_queue(self, uri: str) -> None:
        self.queue.append(uri)

    def play_from_queue(self, index: int) -> None:
        self.playing_from = index

    def pause(self) -> None:
        self.paused = True


class FakeShareLinkPlugin:
    def __init__(self, speaker: FakeSoCo) -> None:
        self._speaker = speaker

    def add_share_link_to_queue(self, uri: str) -> None:
        self._speaker.share_links.append(uri)


class FakeSonosAPI(SonosAPI):
    """SonosAPI with fake speaker discovery and playback (no real Sonos needed)."""

    def __init__(
        self,
        speaker_name: str = "Living Room",
        fake_speaker: FakeSoCo | None = None,
        find_speaker_error: Exception | None = None,
    ) -> None:
        super().__init__(speaker_name)
        self._fake_speaker = fake_speaker
        self._find_speaker_error = find_speaker_error
        if fake_speaker is not None:
            self._speaker = fake_speaker  # type: ignore[assignment]

    def _find_speaker(self) -> FakeSoCo:  # type: ignore[override]
        if self._find_speaker_error is not None:
            raise self._find_speaker_error
        if self._fake_speaker is None:
            raise RuntimeError("No speaker configured in fake")
        return self._fake_speaker

    def _do_play(self, uri: str, shuffle: bool = False) -> None:
        if self._speaker is None:
            raise RuntimeError("Speaker not initialized")
        speaker: FakeSoCo = self._speaker  # type: ignore[assignment]
        speaker.clear_queue()
        if uri.startswith("https://"):
            FakeShareLinkPlugin(speaker).add_share_link_to_queue(uri)
        else:
            speaker.add_uri_to_queue(uri)
        speaker.play_from_queue(0)


# ── Constructor ──────────────────────────────────────────


def test_init_does_not_discover() -> None:
    api = SonosAPI("Living Room")
    assert api._speaker is None
    assert api.speaker_name == "Living Room"


# ── discover() ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_discover_finds_speaker() -> None:
    fake = FakeSoCo("Living Room")
    api = FakeSonosAPI("Living Room", fake_speaker=fake)
    api._speaker = None

    await api.discover()

    assert api._speaker is fake


@pytest.mark.asyncio
async def test_discover_retries_on_failure(monkeypatch) -> None:
    fake = FakeSoCo("Living Room")
    call_count = 0

    api = FakeSonosAPI("Living Room", fake_speaker=fake)
    api._speaker = None

    original_find = api._find_speaker

    def flaky_find() -> FakeSoCo:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Network error")
        return original_find()

    api._find_speaker = flaky_find  # type: ignore[assignment]
    monkeypatch.setattr("tontraeger_client.sonos_api.asyncio.sleep", _instant_sleep)

    await api.discover()

    assert call_count == 2
    assert api._speaker is fake


# ── play_uri() ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_play_uri_native() -> None:
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)

    await api.play_uri("x-sonosapi-radio:s25111?sid=254")

    assert fake.queue == ["x-sonosapi-radio:s25111?sid=254"]
    assert fake.playing_from == 0


@pytest.mark.asyncio
async def test_play_uri_share_link() -> None:
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)

    await api.play_uri("https://open.spotify.com/album/abc123")

    assert fake.share_links == ["https://open.spotify.com/album/abc123"]
    assert fake.queue == []
    assert fake.playing_from == 0


@pytest.mark.asyncio
async def test_play_discovers_if_no_speaker(monkeypatch) -> None:
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)
    api._speaker = None

    monkeypatch.setattr("tontraeger_client.sonos_api.asyncio.sleep", _instant_sleep)

    await api.play_uri("x-sonosapi-radio:test")

    assert api._speaker is fake
    assert fake.queue == ["x-sonosapi-radio:test"]


@pytest.mark.asyncio
async def test_play_error_clears_speaker() -> None:
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)

    def exploding_play(uri: str, shuffle: bool = False) -> None:
        raise RuntimeError("Sonos unreachable")

    api._do_play = exploding_play  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Sonos unreachable"):
        await api.play_uri("x-sonosapi-radio:test")

    assert api._speaker is None


# ── stop_playback() ──────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_pauses() -> None:
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)

    await api.stop_playback()

    assert fake.paused is True


@pytest.mark.asyncio
async def test_stop_no_speaker_is_noop() -> None:
    api = SonosAPI("Living Room")
    assert api._speaker is None

    await api.stop_playback()  # should not raise


@pytest.mark.asyncio
async def test_stop_error_clears_speaker() -> None:
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)

    def exploding_pause() -> None:
        raise RuntimeError("Sonos unreachable")

    fake.pause = exploding_pause  # type: ignore[assignment]

    await api.stop_playback()

    assert api._speaker is None
