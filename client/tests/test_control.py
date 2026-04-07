import asyncio

import pytest

from tontraeger_client.cache import MappingCache
from tontraeger_client.control import PlaybackController, nfc_reader


class DummySonosAPI:
    def __init__(self) -> None:
        self.played_uri: str | None = None
        self.played_shuffle: bool = False
        self.stopped: bool = False
        self.stop_count: int = 0

    async def play_uri(self, uri: str, shuffle: bool = False) -> None:
        self.played_uri = uri
        self.played_shuffle = shuffle

    async def stop_playback(self) -> None:
        self.stopped = True
        self.stop_count += 1


class DummySync:
    def __init__(self) -> None:
        self.reported_tags: list[str] = []

    async def report_unknown_tag(self, tag_uid: str) -> None:
        self.reported_tags.append(tag_uid)


@pytest.fixture
def cache(tmp_path):
    return MappingCache(str(tmp_path / "mappings.json"))


# ── handle_present ───────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_present_plays_uri(cache) -> None:
    cache.update([{"tag_uid": "04:ab:cd:12:34:56:78", "media_uri": "x-sonosapi-radio:s25111", "name": "", "shuffle": False}])
    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache)

    await controller.handle_present("04:ab:cd:12:34:56:78")

    assert sonos.played_uri == "x-sonosapi-radio:s25111"
    assert sonos.played_shuffle is False
    assert not sonos.stopped


@pytest.mark.asyncio
async def test_handle_present_plays_with_shuffle(cache) -> None:
    cache.update([{"tag_uid": "04:ab:cd:12:34:56:78", "media_uri": "spotify:playlist:xyz", "name": "Radio", "shuffle": True}])
    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache)

    await controller.handle_present("04:ab:cd:12:34:56:78")

    assert sonos.played_uri == "spotify:playlist:xyz"
    assert sonos.played_shuffle is True


@pytest.mark.asyncio
async def test_handle_present_unknown_reports(cache) -> None:
    """Unknown tag fires report_unknown_tag as a background task."""
    sonos = DummySonosAPI()
    sync = DummySync()
    controller = PlaybackController(sonos, cache, sync=sync)

    await controller.handle_present("unknown_tag")
    # Let the fire-and-forget task run
    await asyncio.sleep(0)

    assert sync.reported_tags == ["unknown_tag"]
    assert sonos.played_uri is None


@pytest.mark.asyncio
async def test_handle_present_unknown_without_sync(cache) -> None:
    """No crash when sync is None and tag is unknown."""
    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache, sync=None)

    await controller.handle_present("unknown_tag")

    assert sonos.played_uri is None


# ── handle_removed ───────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_removed_pauses(cache) -> None:
    cache.update([{"tag_uid": "04:ab:cd:12:34:56:78", "media_uri": "x-radio:test", "name": "", "shuffle": False}])
    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache)

    await controller.handle_present("04:ab:cd:12:34:56:78")
    await controller.handle_removed("04:ab:cd:12:34:56:78")

    assert sonos.stop_count == 1


@pytest.mark.asyncio
async def test_handle_removed_ignored_if_tag_never_played(cache) -> None:
    """REMOVED for a tag that was never placed must not call stop_playback."""
    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache)

    await controller.handle_removed("04:ab:cd:12:34:56:78")

    assert sonos.stop_count == 0


@pytest.mark.asyncio
async def test_handle_removed_stops_currently_playing_tag(cache) -> None:
    """REMOVED for the tag that is currently playing must call stop_playback."""
    cache.update([{"tag_uid": "04:aa:aa:aa:aa:aa:aa", "media_uri": "x-radio:test", "name": "", "shuffle": False}])
    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache)

    await controller.handle_present("04:aa:aa:aa:aa:aa:aa")
    await controller.handle_removed("04:aa:aa:aa:aa:aa:aa")

    assert sonos.stop_count == 1


@pytest.mark.asyncio
async def test_handle_removed_ignored_for_different_tag(cache) -> None:
    """REMOVED for a tag other than the one currently playing must be ignored."""
    cache.update([{"tag_uid": "04:aa:aa:aa:aa:aa:aa", "media_uri": "x-radio:test", "name": "", "shuffle": False}])
    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache)

    await controller.handle_present("04:aa:aa:aa:aa:aa:aa")
    await controller.handle_removed("04:bb:bb:bb:bb:bb:bb")  # different tag

    assert sonos.stop_count == 0


@pytest.mark.asyncio
async def test_handle_removed_ignored_after_failed_play(cache) -> None:
    """REMOVED for a tag whose play_uri raised must not call stop_playback."""
    cache.update([{"tag_uid": "04:aa:aa:aa:aa:aa:aa", "media_uri": "x-radio:test", "name": "", "shuffle": False}])
    sonos = DummySonosAPI()

    async def failing_play(uri: str, shuffle: bool = False) -> None:
        raise RuntimeError("Sonos unreachable")

    sonos.play_uri = failing_play  # type: ignore[assignment]
    controller = PlaybackController(sonos, cache)

    try:
        await controller.handle_present("04:aa:aa:aa:aa:aa:aa")
    except Exception:
        pass

    await controller.handle_removed("04:aa:aa:aa:aa:aa:aa")

    assert sonos.stop_count == 0


# ── nfc_reader ───────────────────────────────────────────


class FakeStreamReader:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)
        self._index = 0

    async def readline(self) -> bytes:
        if self._index < len(self._lines):
            line = self._lines[self._index]
            self._index += 1
            return line
        return b""  # EOF


class FakeProcess:
    """Fake asyncio.subprocess.Process for testing nfc_reader."""

    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = FakeStreamReader(lines)
        self.pid = 12345
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15  # SIGTERM

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9  # SIGKILL


async def _run_nfc_reader_with_fake_daemon(
    cache,
    lines: list[bytes],
    sonos: DummySonosAPI | None = None,
    sync: DummySync | None = None,
    max_restarts: int = 0,
) -> tuple[PlaybackController, DummySonosAPI, FakeProcess]:
    """Run nfc_reader against a fake daemon that emits the given lines.

    The fake daemon produces `lines` on stdout, then hits EOF.
    After `max_restarts` restarts, raises CancelledError to stop the loop.
    """
    if sonos is None:
        sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache, sync=sync)

    proc = FakeProcess(lines)
    restart_count = 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        nonlocal restart_count
        if restart_count > max_restarts:
            raise asyncio.CancelledError()
        restart_count += 1
        return proc

    import tontraeger_client.control as control_module

    # Speed up backoff sleep
    async def instant_sleep(s: float) -> None:
        pass

    old_fn = asyncio.create_subprocess_exec
    old_sleep = asyncio.sleep
    asyncio.create_subprocess_exec = fake_create_subprocess_exec  # type: ignore[assignment]
    control_module.asyncio.sleep = instant_sleep  # type: ignore[attr-defined]

    try:
        with pytest.raises(asyncio.CancelledError):
            await nfc_reader(controller, "/fake/nfc-daemon")
    finally:
        asyncio.create_subprocess_exec = old_fn  # type: ignore[assignment]
        control_module.asyncio.sleep = old_sleep  # type: ignore[attr-defined]

    return controller, sonos, proc


@pytest.mark.asyncio
async def test_nfc_reader_dispatches_present(cache) -> None:
    cache.update([{"tag_uid": "04:ab:cd:12:34:56:78", "media_uri": "x-radio:test", "name": "", "shuffle": False}])
    lines = [b"PRESENT 04:ab:cd:12:34:56:78\n"]

    _, sonos, _ = await _run_nfc_reader_with_fake_daemon(cache, lines)

    assert sonos.played_uri == "x-radio:test"


@pytest.mark.asyncio
async def test_nfc_reader_dispatches_removed(cache) -> None:
    cache.update([{"tag_uid": "04:ab:cd:12:34:56:78", "media_uri": "x-radio:test", "name": "", "shuffle": False}])
    lines = [b"PRESENT 04:ab:cd:12:34:56:78\n", b"REMOVED 04:ab:cd:12:34:56:78\n"]

    _, sonos, _ = await _run_nfc_reader_with_fake_daemon(cache, lines)

    assert sonos.stopped


@pytest.mark.asyncio
async def test_nfc_reader_restarts_on_eof(cache) -> None:
    """Daemon exit (EOF) triggers restart with backoff."""
    restart_count = 0

    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache)

    async def counting_subprocess_exec(*args, **kwargs):
        nonlocal restart_count
        restart_count += 1
        if restart_count >= 3:
            raise asyncio.CancelledError()
        return FakeProcess([])  # immediate EOF

    import tontraeger_client.control as control_module

    async def instant_sleep(s: float) -> None:
        pass

    old_fn = asyncio.create_subprocess_exec
    old_sleep = asyncio.sleep
    asyncio.create_subprocess_exec = counting_subprocess_exec  # type: ignore[assignment]
    control_module.asyncio.sleep = instant_sleep  # type: ignore[attr-defined]

    try:
        with pytest.raises(asyncio.CancelledError):
            await nfc_reader(controller, "/fake/nfc-daemon")
    finally:
        asyncio.create_subprocess_exec = old_fn  # type: ignore[assignment]
        control_module.asyncio.sleep = old_sleep  # type: ignore[attr-defined]

    assert restart_count == 3


@pytest.mark.asyncio
async def test_nfc_reader_terminates_child_on_exit(cache) -> None:
    """When cancelled while daemon is still running, terminate() is called."""

    class HangingProcess(FakeProcess):
        """A process that blocks on readline forever (simulating a live daemon)."""

        def __init__(self) -> None:
            super().__init__([])
            self.stdout = self  # type: ignore[assignment]
            self.returncode = None  # still running

        async def readline(self) -> bytes:
            # Block until cancelled — simulates waiting for daemon output
            await asyncio.sleep(999)
            return b""  # unreachable

        async def wait(self) -> int:
            # After terminate(), immediately return
            self.returncode = -15
            return -15

    proc = HangingProcess()
    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache)

    old_fn = asyncio.create_subprocess_exec

    async def fake_create_subprocess_exec(*args, **kwargs):
        return proc

    asyncio.create_subprocess_exec = fake_create_subprocess_exec  # type: ignore[assignment]

    try:
        task = asyncio.create_task(nfc_reader(controller, "/fake/nfc-daemon"))
        # Let the reader start and block on readline
        await asyncio.sleep(0)
        # Cancel from outside (simulates SIGTERM)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        asyncio.create_subprocess_exec = old_fn  # type: ignore[assignment]

    assert proc.terminated


@pytest.mark.asyncio
async def test_nfc_reader_backoff_resets_after_output(cache) -> None:
    """Backoff resets after the first line from the daemon, not just after spawn."""
    sleep_values: list[float] = []
    call_count = 0

    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache)

    async def fake_subprocess_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First run: emit a line then EOF — should reset backoff
            return FakeProcess([b"REMOVED 04:00:00:00:00:00:00\n"])
        elif call_count == 2:
            # Second run: immediate EOF — should use reset backoff (1s)
            return FakeProcess([])
        else:
            raise asyncio.CancelledError()

    import tontraeger_client.control as control_module

    old_fn = asyncio.create_subprocess_exec
    old_sleep = asyncio.sleep
    asyncio.create_subprocess_exec = fake_subprocess_exec  # type: ignore[assignment]

    async def tracking_sleep(s: float) -> None:
        sleep_values.append(s)

    control_module.asyncio.sleep = tracking_sleep  # type: ignore[attr-defined]

    try:
        with pytest.raises(asyncio.CancelledError):
            await nfc_reader(controller, "/fake/nfc-daemon")
    finally:
        asyncio.create_subprocess_exec = old_fn  # type: ignore[assignment]
        control_module.asyncio.sleep = old_sleep  # type: ignore[attr-defined]

    # First restart sleep should be 1.0 (reset by output from run 1)
    assert sleep_values[0] == 1.0


@pytest.mark.asyncio
async def test_nfc_reader_handler_error_continues(cache) -> None:
    """A Sonos error in handle_present must not restart the daemon."""
    cache.update([
        {"tag_uid": "04:aa:aa:aa:aa:aa:aa", "media_uri": "x-radio:first", "name": "", "shuffle": False},
        {"tag_uid": "04:bb:bb:bb:bb:bb:bb", "media_uri": "x-radio:second", "name": "", "shuffle": False},
    ])

    sonos = DummySonosAPI()
    call_count = 0
    original_play_uri = sonos.play_uri

    async def flaky_play(uri: str, shuffle: bool = False) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Sonos unreachable")
        await original_play_uri(uri, shuffle=shuffle)

    sonos.play_uri = flaky_play  # type: ignore[assignment]

    lines = [
        b"PRESENT 04:aa:aa:aa:aa:aa:aa\n",  # will fail
        b"PRESENT 04:bb:bb:bb:bb:bb:bb\n",  # should still be dispatched
    ]

    _, _, _ = await _run_nfc_reader_with_fake_daemon(cache, lines, sonos=sonos)

    # Second play should have succeeded despite first failing
    assert sonos.played_uri == "x-radio:second"


@pytest.mark.asyncio
async def test_nfc_reader_malformed_line_logged(cache) -> None:
    """Garbage lines are logged but don't crash the reader."""
    cache.update([{"tag_uid": "04:ab:cd:12:34:56:78", "media_uri": "x-radio:ok", "name": "", "shuffle": False}])
    lines = [
        b"GARBAGE nonsense\n",
        b"\n",
        b"PRESENT\n",  # missing UID
        b"PRESENT 04:ab:cd:12:34:56:78\n",  # valid — should still work
    ]

    _, sonos, _ = await _run_nfc_reader_with_fake_daemon(cache, lines)

    assert sonos.played_uri == "x-radio:ok"


@pytest.mark.asyncio
async def test_nfc_reader_non_utf8_does_not_crash(cache) -> None:
    """Binary garbage from the daemon is handled, not crashed on."""
    cache.update([{"tag_uid": "04:ab:cd:12:34:56:78", "media_uri": "x-radio:ok", "name": "", "shuffle": False}])
    lines = [
        b"\xff\xfe PRESENT garbage\n",  # invalid UTF-8
        b"PRESENT 04:ab:cd:12:34:56:78\n",  # valid — should still work
    ]

    _, sonos, _ = await _run_nfc_reader_with_fake_daemon(cache, lines)

    assert sonos.played_uri == "x-radio:ok"


@pytest.mark.asyncio
async def test_nfc_reader_daemon_not_found(cache) -> None:
    """Missing binary triggers backoff, not crash."""
    sonos = DummySonosAPI()
    controller = PlaybackController(sonos, cache)

    sleep_values: list[float] = []
    call_count = 0

    import tontraeger_client.control as control_module

    old_sleep = asyncio.sleep

    async def tracking_sleep(s: float) -> None:
        nonlocal call_count
        sleep_values.append(s)
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    control_module.asyncio.sleep = tracking_sleep  # type: ignore[attr-defined]

    try:
        with pytest.raises(asyncio.CancelledError):
            await nfc_reader(controller, "/nonexistent/nfc-daemon")
    finally:
        control_module.asyncio.sleep = old_sleep  # type: ignore[attr-defined]

    # Should have retried with increasing backoff
    assert len(sleep_values) == 2
    assert sleep_values[0] == 1.0
    assert sleep_values[1] == 2.0
