import asyncio

import pytest
import requests
from soco.exceptions import SoCoUPnPException

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
        self.playing = False
        self.paused = False
        self.share_links: list[str] = []
        self.play_mode: str = ""
        self.call_order: list[str] = []
        self.group = _FakeGroup(self)

    def clear_queue(self) -> None:
        self.queue.clear()
        self.share_links.clear()
        self.call_order.clear()

    def add_uri_to_queue(self, uri: str) -> None:
        self.queue.append(uri)

    def play_from_queue(self, index: int) -> None:
        self.playing_from = index
        self.call_order.append("play_from_queue")

    def play(self) -> None:
        self.playing = True
        self.call_order.append("play")

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
        speaker.play()


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
async def test_play_uri_sets_shuffle_mode() -> None:
    fake = FakeSoCo()
    api = SonosAPI("Living Room")
    api._speaker = fake  # type: ignore[assignment]

    await api.play_uri("x-sonosapi-radio:s123", shuffle=True)

    assert fake.play_mode == "SHUFFLE"


@pytest.mark.asyncio
async def test_play_uri_sets_normal_mode() -> None:
    fake = FakeSoCo()
    api = SonosAPI("Living Room")
    api._speaker = fake  # type: ignore[assignment]

    await api.play_uri("x-sonosapi-radio:s123", shuffle=False)

    assert fake.play_mode == "NORMAL"


@pytest.mark.asyncio
async def test_do_play_play_called_after_queue() -> None:
    """coordinator.play() must come after play_from_queue(0), not before."""
    fake = FakeSoCo()
    api = SonosAPI("Living Room")
    api._speaker = fake  # type: ignore[assignment]

    await api.play_uri("x-sonosapi-radio:s123")

    assert fake.call_order == ["play_from_queue", "play"]


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


@pytest.mark.asyncio
async def test_play_uri_failure_schedules_rediscovery() -> None:
    """After play_uri fails, a background discover() task must run to restore _speaker."""
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)
    api._speaker = fake  # type: ignore[assignment]

    def exploding_play(uri: str, shuffle: bool = False) -> None:
        raise RuntimeError("Sonos unreachable")

    api._do_play = exploding_play  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Sonos unreachable"):
        await api.play_uri("x-sonosapi-radio:test")

    assert api._speaker is None  # correctly cleared during failure

    assert api._pending_discover is not None
    await api._pending_discover
    assert api._speaker is fake  # restored by background discover()


@pytest.mark.asyncio
async def test_play_uri_second_failure_cancels_first_rediscovery() -> None:
    """A second play_uri failure must cancel the in-flight rediscovery before starting a new one."""
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)
    api._speaker = fake  # type: ignore[assignment]

    # Gate that blocks the background discover() so it stays in-flight.
    gate = asyncio.Event()

    def exploding_play(uri: str, shuffle: bool = False) -> None:
        raise RuntimeError("Sonos unreachable")

    async def blocked_discover() -> None:
        """discover() that waits for the gate before doing anything."""
        await gate.wait()

    api._do_play = exploding_play  # type: ignore[assignment]
    api.discover = blocked_discover  # type: ignore[assignment]

    with pytest.raises(RuntimeError):
        await api.play_uri("x-sonosapi-radio:test1")

    first_task = api._pending_discover
    assert first_task is not None
    assert not first_task.done()  # still in-flight (blocked on gate)

    # Restore _speaker so the second play_uri skips inline discover() and
    # goes straight to _do_play (which also raises), hitting the cancel path.
    api._speaker = fake  # type: ignore[assignment]

    with pytest.raises(RuntimeError):
        await api.play_uri("x-sonosapi-radio:test2")

    assert api._pending_discover is not first_task  # new task created
    # Yield to the event loop so the cancelled coroutine can process CancelledError
    # and transition from "cancelling" to "cancelled".
    await asyncio.sleep(0)
    assert first_task.cancelled()  # old task was cancelled

    # Unblock and clean up the second pending task.
    gate.set()
    await api._pending_discover


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
async def test_stop_error_does_not_clear_speaker() -> None:
    """A pause failure must NOT clear _speaker — subsequent REMOVED events must still work."""
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)

    def exploding_pause() -> None:
        raise RuntimeError("Transport error: already stopped")

    fake.pause = exploding_pause  # type: ignore[assignment]

    await api.stop_playback()

    assert api._speaker is fake  # NOT cleared


# ── play_uri() error classification ──────────────────────


def _make_upnp_error() -> SoCoUPnPException:
    return SoCoUPnPException("rejected", "800", "<xml/>")


@pytest.mark.asyncio
async def test_play_uri_readtimeout_keeps_speaker() -> None:
    """ReadTimeout means speaker is reachable but stalling — don't drop the reference."""
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)

    def stalling_play(uri: str, shuffle: bool = False) -> None:
        raise requests.ReadTimeout("speaker timed out")

    api._do_play = stalling_play  # type: ignore[assignment]

    with pytest.raises(requests.ReadTimeout):
        await api.play_uri("x-sonosapi-radio:test")

    assert api._speaker is fake
    assert api._pending_discover is None


@pytest.mark.asyncio
async def test_play_uri_upnp_error_keeps_speaker() -> None:
    """SoCoUPnPException means the speaker rejected the action — don't drop the reference."""
    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)

    def rejecting_play(uri: str, shuffle: bool = False) -> None:
        raise _make_upnp_error()

    api._do_play = rejecting_play  # type: ignore[assignment]

    with pytest.raises(SoCoUPnPException):
        await api.play_uri("x-sonosapi-radio:test")

    assert api._speaker is fake
    assert api._pending_discover is None


# ── play_uri() backoff ───────────────────────────────────


class _FakeClock:
    """Monotonic clock that only advances when explicitly told to."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.mark.asyncio
async def test_play_uri_first_failure_does_not_delay_next_attempt(monkeypatch) -> None:
    """A single glitch must not block the next tap — first failure incurs no penalty."""
    clock = _FakeClock()
    monkeypatch.setattr("tontraeger_client.sonos_api.time.monotonic", clock)

    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)
    calls = 0

    def maybe_failing_play(uri: str, shuffle: bool = False) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise requests.ReadTimeout("transient")

    api._do_play = maybe_failing_play  # type: ignore[assignment]

    with pytest.raises(requests.ReadTimeout):
        await api.play_uri("x-sonosapi-radio:a")

    # No clock advance — second call is allowed immediately.
    await api.play_uri("x-sonosapi-radio:b")
    assert calls == 2


@pytest.mark.asyncio
async def test_play_uri_second_failure_imposes_backoff(monkeypatch) -> None:
    """After two consecutive failures, the next attempt is blocked for ~2s."""
    clock = _FakeClock()
    monkeypatch.setattr("tontraeger_client.sonos_api.time.monotonic", clock)

    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)

    def always_fails(uri: str, shuffle: bool = False) -> None:
        raise requests.ReadTimeout("upstream broken")

    api._do_play = always_fails  # type: ignore[assignment]

    with pytest.raises(requests.ReadTimeout):
        await api.play_uri("x-sonosapi-radio:a")
    with pytest.raises(requests.ReadTimeout):
        await api.play_uri("x-sonosapi-radio:b")

    # Third call within the 2s window must short-circuit before _do_play.
    fake.call_order.clear()
    with pytest.raises(RuntimeError, match="backoff"):
        await api.play_uri("x-sonosapi-radio:c")
    assert fake.call_order == []

    # After advancing past the backoff window, the call goes through (and fails again).
    clock.advance(2.0)
    with pytest.raises(requests.ReadTimeout):
        await api.play_uri("x-sonosapi-radio:d")


@pytest.mark.asyncio
async def test_play_uri_backoff_is_tag_independent(monkeypatch) -> None:
    """Backoff applies to the speaker, not a specific URI — different URIs share the window."""
    clock = _FakeClock()
    monkeypatch.setattr("tontraeger_client.sonos_api.time.monotonic", clock)

    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)
    attempts: list[str] = []

    def always_fails(uri: str, shuffle: bool = False) -> None:
        attempts.append(uri)
        raise requests.ReadTimeout("upstream broken")

    api._do_play = always_fails  # type: ignore[assignment]

    with pytest.raises(requests.ReadTimeout):
        await api.play_uri("uri-A")
    with pytest.raises(requests.ReadTimeout):
        await api.play_uri("uri-B")

    # A different URI within the window is also blocked.
    with pytest.raises(RuntimeError, match="backoff"):
        await api.play_uri("uri-C")
    assert attempts == ["uri-A", "uri-B"]


@pytest.mark.asyncio
async def test_play_uri_success_resets_backoff(monkeypatch) -> None:
    """A successful play after failures resets the counter so a later glitch isn't penalised."""
    clock = _FakeClock()
    monkeypatch.setattr("tontraeger_client.sonos_api.time.monotonic", clock)

    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)
    calls = 0

    def flaky_play(uri: str, shuffle: bool = False) -> None:
        nonlocal calls
        calls += 1
        if calls in (1, 2, 4):
            raise requests.ReadTimeout("flaky")

    api._do_play = flaky_play  # type: ignore[assignment]

    with pytest.raises(requests.ReadTimeout):
        await api.play_uri("uri-A")
    with pytest.raises(requests.ReadTimeout):
        await api.play_uri("uri-B")
    clock.advance(2.0)
    # 3rd call succeeds → reset.
    await api.play_uri("uri-C")
    assert api._consecutive_failures == 0
    # 4th call fails but is the FIRST failure of a fresh streak, so no delay.
    with pytest.raises(requests.ReadTimeout):
        await api.play_uri("uri-D")
    # And the next attempt is immediately allowed.
    await api.play_uri("uri-E")


@pytest.mark.asyncio
async def test_play_uri_backoff_caps_at_30s(monkeypatch) -> None:
    """The backoff window never exceeds 30s, even after many consecutive failures."""
    clock = _FakeClock()
    monkeypatch.setattr("tontraeger_client.sonos_api.time.monotonic", clock)

    fake = FakeSoCo()
    api = FakeSonosAPI(fake_speaker=fake)

    def always_fails(uri: str, shuffle: bool = False) -> None:
        raise requests.ReadTimeout("flaky")

    api._do_play = always_fails  # type: ignore[assignment]

    # Drive ten consecutive failures, advancing past each window before the next call.
    for _ in range(10):
        before = clock.now
        with pytest.raises(requests.ReadTimeout):
            await api.play_uri("uri")
        imposed = api._next_attempt_at - before
        assert imposed <= 30.0
        clock.advance(max(imposed, 0.1))
