# Fix Playback Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three certain and one uncertain bug that cause Sonos playback to not start or not stop reliably when NFC tags are placed and removed.

**Architecture:** All changes are in the Python asyncio client. `SonosAPI` (`sonos_api.py`) manages the SoCo connection and is the source of all three certain bugs; `PlaybackController` (`control.py`) handles tag events and is the source of the uncertain race-condition bug. No server changes needed.

**Tech Stack:** Python 3.11+, asyncio, SoCo (Sonos), pytest-asyncio, uv

---

### Task 1: Fix `stop_playback()` clearing `_speaker` on benign transport errors

**Goal:** Ensure that a failed `pause()` call (e.g. Sonos is STOPPED/TRANSITIONING) does not discard the speaker reference, so subsequent REMOVED events still call `stop_playback` rather than short-circuiting on `_speaker is None`.

**Files:**
- Modify: `client/tontraeger_client/sonos_api.py:82-84`
- Test: `client/tests/test_sonos_api.py`

**Acceptance Criteria:**
- [ ] `stop_playback()` does not set `self._speaker = None` when `pause()` raises
- [ ] `stop_playback()` called twice in a row (first call raises, second call doesn't) still pauses on the second call
- [ ] Existing test `test_stop_pauses` still passes
- [ ] `make check` passes

**Verify:** `cd client && uv run pytest tests/test_sonos_api.py -v` → all tests green

**Steps:**

- [ ] **Step 1: Write the failing test**

In `client/tests/test_sonos_api.py`, replace `test_stop_error_clears_speaker` with:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd client && uv run pytest tests/test_sonos_api.py::test_stop_error_does_not_clear_speaker -v`
Expected: FAIL — `AssertionError: assert None is <FakeSoCo object>`

- [ ] **Step 3: Write minimal implementation**

In `client/tontraeger_client/sonos_api.py`, change `stop_playback()` from:

```python
    except Exception as e:
        logger.error("stop_playback failed: %s — clearing speaker for rediscovery", e)
        self._speaker = None
```

to:

```python
    except Exception as e:
        logger.error("stop_playback failed: %s", e)
        # Do NOT clear _speaker. A transport error (already stopped, transitioning)
        # does not mean the speaker is unreachable. Clearing it here causes the next
        # REMOVED event to silently short-circuit on `if self._speaker is None: return`.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd client && uv run pytest tests/test_sonos_api.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add client/tontraeger_client/sonos_api.py client/tests/test_sonos_api.py
git commit -m "fix: stop_playback must not clear speaker on transport errors

A pause() failure (Sonos already STOPPED or TRANSITIONING) does not mean
the speaker is unreachable. Clearing _speaker caused every subsequent
REMOVED event to silently return early instead of pausing playback."
```

---

### Task 2: Fix `play_uri()` failure leaving `_speaker` unrecoverable for `stop_playback`

**Goal:** After `play_uri()` fails and clears `_speaker`, immediately schedule a background rediscovery so that a REMOVED event arriving before the next PRESENT still has a speaker to pause.

**Files:**
- Modify: `client/tontraeger_client/sonos_api.py:__init__, 68-71`
- Test: `client/tests/test_sonos_api.py`

**Acceptance Criteria:**
- [ ] After `play_uri()` raises, `_speaker` is still None (clearing is correct)
- [ ] After awaiting all pending tasks, `_speaker` is repopulated by background rediscovery
- [ ] `make check` passes

**Verify:** `cd client && uv run pytest tests/test_sonos_api.py -v` → all tests green

**Steps:**

- [ ] **Step 1: Write the failing test**

In `client/tests/test_sonos_api.py`, add after the `test_play_error_clears_speaker` test:

```python
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

    # Wait for the background rediscovery task to complete
    import asyncio
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    assert api._speaker is fake  # restored by background discover()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd client && uv run pytest tests/test_sonos_api.py::test_play_uri_failure_schedules_rediscovery -v`
Expected: FAIL — `AssertionError: assert None is <FakeSoCo object>` (background task not scheduled)

- [ ] **Step 3: Write minimal implementation**

In `client/tontraeger_client/sonos_api.py`:

Add to `__init__`:
```python
self._pending_discover: asyncio.Task[None] | None = None
```

Change `play_uri()` except block from:
```python
        except Exception as e:
            logger.error("play_uri failed: %s — clearing speaker for rediscovery", e)
            self._speaker = None
            raise
```
to:
```python
        except Exception as e:
            logger.error("play_uri failed: %s — clearing speaker for rediscovery", e)
            self._speaker = None
            # Immediately kick off rediscovery so stop_playback() remains functional
            # for any REMOVED event that arrives before the next PRESENT.
            # Store reference to prevent GC before the task completes.
            self._pending_discover = asyncio.create_task(self.discover())
            raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd client && uv run pytest tests/test_sonos_api.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add client/tontraeger_client/sonos_api.py client/tests/test_sonos_api.py
git commit -m "fix: schedule rediscovery after play_uri failure

The background discover_task in main.py exits once the speaker is found.
After play_uri clears _speaker on failure, there was no mechanism to
restore it, so REMOVED events would silently do nothing until the next
PRESENT triggered inline discovery. Now schedules asyncio.create_task
immediately so stop_playback() keeps working."
```

---

### Task 3: Fix `play_from_queue(0)` not always starting playback

**Goal:** Add an explicit `coordinator.play()` call after `coordinator.play_from_queue(0)` in `_do_play()` to guard against Sonos silently discarding the internal `play()` during TRANSITIONING state.

**Files:**
- Modify: `client/tontraeger_client/sonos_api.py:44`
- Modify: `client/tests/test_sonos_api.py` (extend `FakeSoCo`, update `FakeSonosAPI._do_play`)

**Acceptance Criteria:**
- [ ] `coordinator.play()` is called after `coordinator.play_from_queue(0)` in `_do_play()`
- [ ] `FakeSoCo.play()` is implemented and tracks invocation
- [ ] `FakeSonosAPI._do_play` calls `speaker.play()` to stay aligned with production
- [ ] `make check` passes

**Verify:** `cd client && uv run pytest tests/test_sonos_api.py -v` → all tests green

**Steps:**

- [ ] **Step 1: Extend `FakeSoCo` with `play()` tracking**

In `client/tests/test_sonos_api.py`, update `FakeSoCo`:

```python
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
```

- [ ] **Step 2: Write the failing tests**

In `client/tests/test_sonos_api.py`, add after `test_play_uri_sets_normal_mode`:

```python
@pytest.mark.asyncio
async def test_do_play_calls_play_explicitly() -> None:
    """_do_play must call coordinator.play() after play_from_queue to ensure playback starts."""
    fake = FakeSoCo()
    api = SonosAPI("Living Room")
    api._speaker = fake  # type: ignore[assignment]

    await api.play_uri("x-sonosapi-radio:s123")

    assert fake.playing is True


@pytest.mark.asyncio
async def test_do_play_play_called_after_queue() -> None:
    """coordinator.play() must come after play_from_queue(0), not before."""
    fake = FakeSoCo()
    api = SonosAPI("Living Room")
    api._speaker = fake  # type: ignore[assignment]

    await api.play_uri("x-sonosapi-radio:s123")

    assert fake.call_order == ["play_from_queue", "play"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd client && uv run pytest tests/test_sonos_api.py::test_do_play_calls_play_explicitly tests/test_sonos_api.py::test_do_play_play_called_after_queue -v`
Expected: FAIL — `assert False is True` and `assert ['play_from_queue'] == ['play_from_queue', 'play']`

- [ ] **Step 4: Write minimal implementation**

In `client/tontraeger_client/sonos_api.py`, in `_do_play()`, change:

```python
        coordinator.play_from_queue(0)
```

to:

```python
        coordinator.play_from_queue(0)
        # play_from_queue internally calls play(), but Sonos can discard it when the
        # device is in TRANSITIONING state (e.g. after clearing the queue mid-play).
        # An explicit play() is a no-op if already playing and fixes the race.
        coordinator.play()
```

Also update `FakeSonosAPI._do_play` in `client/tests/test_sonos_api.py` to stay aligned:

```python
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
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `cd client && uv run pytest tests/test_sonos_api.py -v`
Expected: all tests PASS

- [ ] **Step 6: Run full check**

Run: `cd /home/user/tontraeger && make check`
Expected: all lint, typecheck, and tests pass

- [ ] **Step 7: Commit**

```bash
git add client/tontraeger_client/sonos_api.py client/tests/test_sonos_api.py
git commit -m "fix: call coordinator.play() explicitly after play_from_queue

play_from_queue(0) internally calls play(), but Sonos firmware silently
discards it when the device is in TRANSITIONING state (e.g. queue cleared
while previously playing). Media loads but transport stays PAUSED.
An explicit play() is idempotent when already playing."
```

---

### Task 4: Fix PRESENT/REMOVED race with `_playing_tag` state (conditional)

> **⚠️ Conditional:** Deploy Tasks 1–3 first and observe behaviour across several tag-swap sessions on hardware. Only implement this task if "place tag → no play" persists despite A–C fixes.

**Goal:** Track which tag is currently playing in `PlaybackController` so that a stale REMOVED event (buffered while `play_uri` was executing) doesn't pause immediately after a successful play.

**Files:**
- Modify: `client/tontraeger_client/control.py`
- Test: `client/tests/test_control.py`

**Acceptance Criteria:**
- [ ] REMOVED for a tag that was never played is a no-op
- [ ] REMOVED for the currently-playing tag stops playback
- [ ] REMOVED for a different tag (while tag A is playing) is ignored
- [ ] After `play_uri` raises, `_playing_tag` is not set; REMOVED for that tag is a no-op
- [ ] `make check` passes

**Verify:** `cd client && uv run pytest tests/test_control.py -v` → all tests green

**Steps:**

- [ ] **Step 1: Add `stop_count` to `DummySonosAPI`**

In `client/tests/test_control.py`, update `DummySonosAPI`:

```python
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
```

- [ ] **Step 2: Write the failing tests**

In `client/tests/test_control.py`, add:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd client && uv run pytest tests/test_control.py::test_handle_removed_ignored_if_tag_never_played tests/test_control.py::test_handle_removed_ignored_for_different_tag -v`
Expected: FAIL

- [ ] **Step 4: Write minimal implementation**

In `client/tontraeger_client/control.py`, update `PlaybackController`:

```python
class PlaybackController:
    def __init__(
        self,
        sonos_api: SonosAPI,
        cache: MappingCache,
        sync: MappingSync | None = None,
    ) -> None:
        self.sonos_api = sonos_api
        self.cache = cache
        self.sync = sync
        self._pending_report: asyncio.Task[None] | None = None
        self._playing_tag: str | None = None

    async def handle_present(self, tag_uid: str) -> None:
        """A tag was placed on the reader. Play its music, or report it as unknown."""
        uri = self.cache.get_uri(tag_uid)
        if uri is None:
            logger.info("Unknown tag: %s", tag_uid)
            if self.sync is not None:
                self._pending_report = asyncio.create_task(self.sync.report_unknown_tag(tag_uid))
            return
        name = self.cache.get_name(tag_uid) or tag_uid
        shuffle = self.cache.get_shuffle(tag_uid)
        logger.info("Playing %s (%s)%s", name, uri, " [shuffle]" if shuffle else "")
        await self.sonos_api.play_uri(uri, shuffle=shuffle)
        self._playing_tag = tag_uid  # only set on success

    async def handle_removed(self, tag_uid: str) -> None:
        """A tag was removed from the reader. Pause playback if it was the playing tag."""
        if self._playing_tag != tag_uid:
            logger.debug("Ignoring REMOVED for %s (currently playing: %s)", tag_uid, self._playing_tag)
            return
        name = self.cache.get_name(tag_uid) or tag_uid
        logger.info("Pausing (%s removed)", name)
        self._playing_tag = None
        await self.sonos_api.stop_playback()
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `cd client && uv run pytest tests/test_control.py -v`
Expected: all tests PASS

- [ ] **Step 6: Run full check**

Run: `cd /home/user/tontraeger && make check`
Expected: all lint, typecheck, and tests pass

- [ ] **Step 7: Commit**

```bash
git add client/tontraeger_client/control.py client/tests/test_control.py
git commit -m "fix: track playing tag to ignore stale REMOVED events

Events are processed sequentially. If REMOVED arrives buffered during a
slow play_uri call, it would pause immediately after play. Now REMOVED
is only acted on when the removed tag matches the last successfully
started tag."
```

---

## Execution Order

Tasks 1–3 are independent fixes to `sonos_api.py`; implement them in order (each builds confidence for the next). Task 4 is conditional on hardware testing and touches `control.py`.

1. Task 1 → deploy → verify removals now stop reliably
2. Task 2 → deploy → verify removals after a failed play now stop
3. Task 3 → deploy → verify placement now reliably starts playback
4. Observe on hardware for several sessions
5. Task 4 → only if "place tag → no play" symptom persists

## Architectural Notes

**Task 1 risk:** Not clearing `_speaker` on pause failure means a genuinely unreachable speaker won't be rediscovered via `stop_playback`. Recovery happens on the next `play_uri` call, which still clears `_speaker` and schedules rediscovery (Task 2 fix). One extra failure before recovery — acceptable.

**Task 2 risk:** Two `discover()` coroutines may run concurrently if a PRESENT arrives before the background task completes. Both find the same speaker; the write to `_speaker` is idempotent.

**Task 3:** The extra `coordinator.play()` adds one UPnP round-trip (~50–100ms). Negligible at human interaction speeds.

**Task 4 limitation:** `_playing_tag` guards against the multi-tag-swap race (REMOVED for tag A arrives after tag B starts). It does NOT fix the within-play-window race (REMOVED buffered during `play_uri` for the same tag — `_playing_tag` is set AFTER `play_uri` returns, so REMOVED fires and matches). If that symptom persists, a timestamp-based cooldown would be needed.
