# Playback Reliability Bug Fixes

## Overview

Four bugs have been identified in the Raspberry Pi Sonos controller (tontraeger client). Three are certain
production bugs (A, B, C), one is a probable race condition (D) to implement only if A–C don't resolve the
symptom after hardware testing.

All fixes follow TDD: write the failing test first, then make the minimal change to pass it.
All tests use simple fakes, not `unittest.mock`, matching the project's "test fakes over mocks" convention
(see `client/CLAUDE.md`).

Run `make check` (lint + typecheck + test) after each step before proceeding.

---

## Bug A — `stop_playback()` clears `_speaker` on benign Sonos errors

**File:** `client/tontraeger_client/sonos_api.py`
**Lines:** 73–84

```python
async def stop_playback(self) -> None:
    """Pause playback. Does nothing if no speaker has been found yet."""
    if self._speaker is None:
        return                                  # line 76

    loop = asyncio.get_running_loop()
    try:
        coordinator = self._speaker.group.coordinator
        await loop.run_in_executor(None, coordinator.pause)
    except Exception as e:
        logger.error("stop_playback failed: %s — clearing speaker for rediscovery", e)
        self._speaker = None                    # line 84  ← BUG
```

**Root cause:** When a Sonos speaker is already STOPPED or TRANSITIONING, `coordinator.pause()` raises a
`SoCoException`. The except branch at line 84 sets `self._speaker = None`. The *next* REMOVED event then
hits the early-return guard at line 76 (`if self._speaker is None: return`) — a silent no-op. Music is
never paused. This is the "later removal doesn't stop" symptom.

**Fix:** On a `pause()` failure, *log and retain* `_speaker` rather than clearing it. Pause errors from a
STOPPED/TRANSITIONING speaker are not speaker-loss errors; the speaker is still reachable. Only clear
`_speaker` if it is genuinely unreachable (connection-level exceptions). The simplest safe fix is to simply
not clear `_speaker` on pause failure — the next `play_uri` call will test reachability and clear if needed.

```python
async def stop_playback(self) -> None:
    if self._speaker is None:
        return
    loop = asyncio.get_running_loop()
    try:
        coordinator = self._speaker.group.coordinator
        await loop.run_in_executor(None, coordinator.pause)
    except Exception as e:
        logger.error("stop_playback failed: %s — will retry next removal", e)
        # Do NOT clear _speaker here. The speaker is still reachable; pause
        # can fail transiently (STOPPED, TRANSITIONING). Clearing _speaker
        # causes the next REMOVED event to be silently dropped.
```

**Tests to write first (TDD):**

1. `test_stop_error_does_not_clear_speaker` — `pause()` raises; assert `api._speaker is fake` (not None).
   This test already *exists* as `test_stop_error_clears_speaker` but currently asserts `_speaker is None`.
   **Change** that assertion to `is fake`. The test name should also be updated to reflect the new contract.

2. `test_stop_subsequent_removed_still_stops_after_first_pause_error` — In `DummySonosAPI`, make
   `stop_playback` raise on the first call. Call `handle_removed` twice on a `PlaybackController`. Assert
   that `stop_playback` was called both times (count invocations via a counter on the fake).

**Exact changes:**
- `client/tontraeger_client/sonos_api.py` lines 82–84: remove `self._speaker = None` from the except block.
- `client/tests/test_sonos_api.py`: rename `test_stop_error_clears_speaker` →
  `test_stop_error_does_not_clear_speaker`; change `assert api._speaker is None` →
  `assert api._speaker is fake`.
- `client/tests/test_control.py`: add `test_stop_subsequent_removed_still_stops_after_first_pause_error`.

---

## Bug B — `play_uri()` clears `_speaker` with no path to rediscovery

**File:** `client/tontraeger_client/sonos_api.py`
**Lines:** 57–71

```python
async def play_uri(self, uri: str, shuffle: bool = False) -> None:
    if self._speaker is None:
        await self.discover()                   # line 63 — inline discover, not the background task

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: self._do_play(uri, shuffle))
    except Exception as e:
        logger.error("play_uri failed: %s — clearing speaker for rediscovery", e)
        self._speaker = None                    # line 70  ← BUG
        raise
```

**Root cause:** When `_do_play` fails, line 70 sets `self._speaker = None`. The intent is to force
rediscovery — but the `discover_task` created in `main.py` already *exited* after it found the speaker the
first time. `SonosAPI.discover()` loops `while self._speaker is None` — once `_speaker` is set it returns
and the task is done. Setting `_speaker = None` after a `play_uri` failure leaves it permanently None with
no background task to rescue it.

**Consequence:** Any REMOVED event after a failed play hits the `if self._speaker is None: return` guard at
`stop_playback` line 76 — silent no-op. `_speaker` stays None until the *next PRESENT event* triggers the
inline `await self.discover()` at line 63.

**Fix:** After clearing `_speaker`, schedule a new one-shot `discover()` coroutine as a fire-and-forget
`asyncio.create_task()`. Mirror the `_pending_report` pattern already used in `control.py`. Store the task
reference to prevent GC.

```python
async def play_uri(self, uri: str, shuffle: bool = False) -> None:
    if self._speaker is None:
        await self.discover()
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: self._do_play(uri, shuffle))
    except Exception as e:
        logger.error("play_uri failed: %s — clearing speaker for rediscovery", e)
        self._speaker = None
        # Reschedule background discovery so stop_playback remains functional
        # for REMOVED events that arrive before the next PRESENT.
        self._pending_discover = asyncio.create_task(self.discover())
        raise
```

Add `self._pending_discover: asyncio.Task[None] | None = None` to `__init__`.

**Tests to write first (TDD):**

1. `test_play_uri_failure_schedules_rediscovery` — Construct a `FakeSonosAPI` with a fake speaker already
   set. Override `_do_play` to raise. Call `play_uri` (expect it to raise). Gather all pending tasks.
   Assert `api._speaker is fake` (discovery completed again).

2. `test_play_uri_failure_then_stop_is_not_noop` — `DummySonosAPI` where `play_uri` raises on first call.
   Wire into `PlaybackController`. Trigger `handle_present`, then `handle_removed` with same tag.
   Assert that `stop_playback` was actually invoked (not short-circuited).

**Exact changes:**
- `client/tontraeger_client/sonos_api.py`:
  - `__init__`: add `self._pending_discover: asyncio.Task[None] | None = None`
  - `play_uri` except block: add `self._pending_discover = asyncio.create_task(self.discover())`
- `client/tests/test_sonos_api.py`: add the two tests above.

---

## Bug C — `play_from_queue(0)` silently fails when speaker is TRANSITIONING

**File:** `client/tontraeger_client/sonos_api.py`
**Lines:** 31–44

```python
def _do_play(self, uri: str, shuffle: bool = False) -> None:
    ...
    coordinator.play_from_queue(0)     # line 44  ← BUG (no explicit play())
```

**Root cause:** `play_from_queue(0)` internally issues a Seek + Play command sequence. When the speaker is
in TRANSITIONING state (e.g., queue was cleared while the device was playing), the Play portion of that
sequence can be silently discarded by the Sonos firmware. Media loads into the queue but transport stays
PAUSED. The well-known workaround is to call `coordinator.play()` *after* `play_from_queue(0)` explicitly.

**Fix:**

```python
coordinator.play_from_queue(0)
coordinator.play()   # guards against TRANSITIONING eating the internal play() call
```

**Tests to write first (TDD):**

1. `test_do_play_calls_explicit_play` — Add `play_called: bool = False` and `def play(self)` to `FakeSoCo`.
   Use `SonosAPI` (not `FakeSonosAPI`) with `_speaker` injected as the fake. Call `play_uri`. Assert
   `fake.play_called is True`.

2. `test_do_play_play_called_after_queue` — Track call order via a `call_order: list[str]` in `FakeSoCo`.
   Assert `"play_from_queue"` appears before `"play"` in the list.

**Note:** Use `SonosAPI` directly (not `FakeSonosAPI`) for these tests so the real `_do_play` runs.
`FakeSonosAPI` overrides `_do_play` entirely. Also update `FakeSonosAPI._do_play` to call `speaker.play()`
after `speaker.play_from_queue(0)` to keep the fake aligned with production behaviour.

**Exact changes:**
- `client/tontraeger_client/sonos_api.py` line 44: add `coordinator.play()` after `play_from_queue(0)`.
- `client/tests/test_sonos_api.py`:
  - Add `play_called: bool`, `call_order: list[str]`, and `def play()` to `FakeSoCo`.
  - Update `FakeSoCo.play_from_queue` to append `"play_from_queue"` to `call_order`.
  - Update `FakeSonosAPI._do_play` to call `speaker.play()` after `speaker.play_from_queue(0)`.
  - Add the two tests above.

---

## Bug D — REMOVED event consumed during slow `play_uri` (race condition)

**Status: Uncertain — implement only if A–C don't resolve the symptom after hardware testing.**

**File:** `client/tontraeger_client/control.py`

**Root cause:** Events are processed sequentially in `nfc_reader`. If `play_uri` takes 1–5 seconds
(Spotify share-link resolution, Sonos round-trip), and the NFC daemon emits REMOVED during that window
(marginal RF contact, 3 × 300ms miss threshold = ~900ms), the REMOVED is buffered in the subprocess pipe.
The moment `handle_present` returns, `nfc_reader` reads the buffered REMOVED and calls `handle_removed` —
pausing what was just played. From the user's perspective: music starts, then immediately stops.

**Fix:** Track which tag UID was most recently played successfully. On REMOVED, only call `stop_playback()`
if the removed tag matches the last-played tag.

```python
class PlaybackController:
    def __init__(self, sonos_api, cache, sync=None):
        ...
        self._playing_tag: str | None = None

    async def handle_present(self, tag_uid: str) -> None:
        ...
        await self.sonos_api.play_uri(uri, shuffle=shuffle)
        self._playing_tag = tag_uid     # only set on success

    async def handle_removed(self, tag_uid: str) -> None:
        if self._playing_tag != tag_uid:
            logger.debug("Ignoring REMOVED for %s (last played: %s)", tag_uid, self._playing_tag)
            return
        self._playing_tag = None
        await self.sonos_api.stop_playback()
```

**Important caveat:** The `_playing_tag` guard protects against the multi-tag-swap scenario (REMOVED for
tag A arrives after tag B has been placed). For the within-play-window scenario, the sequential event loop
means REMOVED is processed *after* `play_uri` returns — at which point `_playing_tag` IS set and
`stop_playback` IS still called. So Bug D's fix does **not** address the within-window race. If that
symptom persists, a timestamp-based cooldown (ignore REMOVED within N ms of a successful play) would be
needed.

**Tests to write first (TDD):**

1. `test_handle_removed_ignored_if_different_tag` — Play tag A, send REMOVED for tag B. Assert no stop.
2. `test_handle_removed_stops_if_same_tag` — Play tag A, send REMOVED for tag A. Assert stop.
3. `test_handle_removed_ignored_if_play_failed` — `play_uri` raises; REMOVED for same tag. Assert no stop.
4. Update `DummySonosAPI` to add `stop_count: int = 0` counter (incremented in `stop_playback`).

**Exact changes:**
- `client/tontraeger_client/control.py`: add `_playing_tag` to `PlaybackController.__init__`, update
  `handle_present` and `handle_removed` as above.
- `client/tests/test_control.py`: add the three tests; add `stop_count` to `DummySonosAPI`.

---

## Execution Order

Each step must pass `make check` before the next begins.

### Step 1 — Fix Bug A

1. Update `test_stop_error_clears_speaker` → `test_stop_error_does_not_clear_speaker` (invert assertion).
   Add `test_stop_subsequent_removed_still_stops_after_first_pause_error` to `test_control.py`.
   Run `make check` — these tests now fail.
2. Remove `self._speaker = None` from `stop_playback` except block. Update log message.
   Run `make check` — green.

### Step 2 — Fix Bug B

1. Add `test_play_uri_failure_schedules_rediscovery` and `test_play_uri_failure_then_stop_is_not_noop`.
   Run `make check` — these tests now fail.
2. Add `_pending_discover` to `__init__`; add `create_task(self.discover())` in `play_uri` except block.
   Run `make check` — green.

### Step 3 — Fix Bug C

1. Extend `FakeSoCo` with `play_called`, `call_order`, and `play()`. Add two new tests.
   Run `make check` — these tests now fail.
2. Add `coordinator.play()` after `play_from_queue(0)`. Update `FakeSonosAPI._do_play` to match.
   Run `make check` — green.

### Step 4 — Fix Bug D (conditional on hardware testing)

Deploy A–C to the Pi and observe across several sessions. Only proceed if the "plays then immediately
stops" symptom persists under marginal RF contact.

1. Add `stop_count` to `DummySonosAPI`. Add three new tests to `test_control.py`.
   Run `make check` — these tests now fail.
2. Add `_playing_tag` state to `PlaybackController`. Update `handle_present` and `handle_removed`.
   Run `make check` — green.

---

## Architectural Risks and Tradeoffs

**Bug A fix may mask genuine speaker loss.** By not clearing `_speaker` on pause failure, we lose one path
to triggering rediscovery. If the speaker goes offline and `pause()` fails for that reason, `_speaker`
stays set and the next `play_uri` will also fail — then *that* failure clears `_speaker` and schedules
rediscovery (Bug B fix). Net effect: one extra failure round-trip before rediscovery. Acceptable.

**Bug B's `create_task(discover())` races with the next PRESENT event.** Two concurrent discovery
coroutines both write to `_speaker`. Both find the same speaker, so the write is idempotent. Low risk.

**Bug C's explicit `play()` adds one UPnP round-trip (~50–100ms).** Negligible for human-scale
interactions. `play()` on an already-playing speaker is a no-op.

**Bug D's `_playing_tag` guard silently drops stops after a failed play.** If `play_uri` raises,
`_playing_tag` is not set. A REMOVED for that tag is ignored. Acceptable — there's nothing playing to
cancel. The user re-places the tag to retry.

**Bug D does not fix the within-play-window race.** If REMOVED is buffered while `play_uri` is executing
and arrives just after it returns, `_playing_tag` is already set and `stop_playback` fires correctly. The
guard only helps the multi-tag-swap scenario. A timestamp-based cooldown would be needed for the
within-window case — defer until hardware evidence confirms it's needed.

---

## Files Modified

| File | Bug(s) | Nature of change |
|---|---|---|
| `client/tontraeger_client/sonos_api.py` | A, B, C | Remove `_speaker = None` in stop; add `create_task(discover())`; add `coordinator.play()` |
| `client/tests/test_sonos_api.py` | A, B, C | Rename+invert A test; add B and C tests; extend `FakeSoCo` |
| `client/tests/test_control.py` | A, B, D | Add regression tests for A and B; add D tests if implemented |
| `client/tontraeger_client/control.py` | D (if) | Add `_playing_tag` state to `PlaybackController` |
