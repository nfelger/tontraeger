# Implementation Plan: PN532 Presence-Based Playback

## What changes

**Before:** Tap an RFID card on the RC522 reader → music plays. Tap again → debounce ignores it for 5 seconds. No way to stop except a special STOP card. Python talks to the RC522 directly via SPI/GPIO.

**After:** Place a card on the PN532 reader → music plays. Remove the card → music pauses. A separate C daemon owns the NFC hardware and tells Python what happened. Python just reacts to events.

```
  BEFORE                              AFTER

  ┌──────────────┐                    ┌───────────────┐
  │  RC522 (SPI) │                    │ PN532 (libnfc)│
  └──────┬───────┘                    └──────┬──── ───┘
         │ blocking read_tag()               │ libnfc C API
  ┌──────▼────────┐                   ┌──────▼───────┐
  │    Python     │                   │   C daemon   │
  │  rfid_reader  │                   │ (child proc) │
  │  + executor   │                   └──────┬───────┘
  └──────┬────────┘                          │ stdout: PRESENT/REMOVED
         │ handle_tag()               ┌──────▼────────┐
  ┌──────▼───────┐                    │    Python     │
  │  Playback    │                    │  nfc_reader   │
  │  Controller  │                    │  coroutine    │
  └──────┬───────┘                    └──────┬────────┘
         │                                   │ handle_present / handle_removed
  ┌──────▼───────┐                    ┌──────▼───────┐
  │    Sonos     │                    │    Sonos     │
  └──────────────┘                    └──────────────┘
```

---

## Tag UID format change

The RC522 returned UIDs as decimal integer strings (`"123456789"`). The PN532/libnfc returns raw bytes. The C daemon will format them as colon-separated lowercase hex (`"04:ab:cd:12:34:56:78"`).

This is a breaking change: existing mappings in the server database use the old format and won't match. All tags must be re-scanned and re-registered after the switch.

---

## File-level change map

| File | Action | Summary |
|---|---|---|
| `nfc-daemon/main.c` | **New** | C daemon: detect tags, check presence, emit events |
| `nfc-daemon/Makefile` | **New** | Build the daemon |
| `tontraeger_client/sonos_api.py` | **Rework** | Make async, lazy discovery with retry, auto-rediscovery on error, remove `get_current_track_uri` |
| `tontraeger_client/sync.py` | **Minor** | `report_unknown_tag` and `run` become async coroutines |
| `tontraeger_client/control.py` | **Rewrite** | `handle_tag` → `handle_present`/`handle_removed`; add `nfc_reader` coroutine |
| `tontraeger_client/main.py` | **Rewrite** | Async entry point, SIGTERM handling, spawns daemon |
| `tontraeger_client/rfid_reader.py` | **Delete** | Replaced by C daemon |
| `tontraeger_client/read_rfid_tag_id.py` | **Delete** | Run the C daemon binary directly for debugging |
| `tontraeger_client/cache.py` | No changes | |
| `tontraeger_client/config.py` | **Update** | Add `NFC_DAEMON_PATH` setting |
| `pyproject.toml` | **Update** | Remove `mfrc522` and `RPi.GPIO` deps |
| `Makefile` | **Update** | Add `build-nfc-daemon` target, remove `read-tag` target |
| `CLAUDE.md` | **Update** | Reflect new architecture |
| `.env.sample` | **Update** | Add `NFC_DAEMON_PATH` |
| `../Makefile` | **Update** | Add daemon build/deploy targets, remove `read-tag` target |
| `tontraeger-client.service` | **Update** | Add `NFC_DAEMON_PATH` env var |

---

## Detailed changes

### 1. C NFC daemon (`nfc-daemon/main.c`)

Standalone C program, spawned by Python as a child process.

**Protocol:** Two line-based messages on stdout:
- `PRESENT 04:ab:cd:12:34:56:78\n` — tag detected
- `REMOVED 04:ab:cd:12:34:56:78\n` — tag gone

UIDs are colon-separated lowercase hex. Logs go to stderr (inherited from the parent process, so they flow to journald under systemd).

**Main loop:**
1. Block on `nfc_initiator_select_passive_target()` until a tag arrives
2. Emit `PRESENT <uid>`
3. Poll for continued presence every ~300ms; declare removed after 3 consecutive misses
4. Emit `REMOVED <uid>`
5. Go to 1

**Error recovery:**
- Device init: retry with exponential backoff (1s → 30s cap)
- Mid-operation device error: close, reopen with backoff
- The daemon never exits voluntarily; Python detects death via EOF

**Build:** `gcc -Wall -Wextra -O2 -o nfc-daemon main.c -lnfc`

stdout must be line-buffered (`setlinebuf(stdout)`) so Python sees events immediately.

**Edge case: tag already on reader at startup.** If the daemon starts (or restarts after a crash) with a tag already present, it detects it as new and emits `PRESENT`. Python plays the URI. This means a daemon restart causes a brief playback restart if a tag is present — acceptable.

**Edge case: multiple tags.** The PN532 talks to one tag at a time. If two tags are placed simultaneously, it picks one non-deterministically. The second is detected only after the first is removed.

### 2. `sonos_api.py` — async with lazy discovery

Four changes to `SonosAPI`:

**a) Constructor no longer discovers.** It just stores the speaker name. Discovery happens in the background or on first use.

**b) All public methods become `async`.** Every SoCo call (which does network I/O) is wrapped in `run_in_executor` so it doesn't block the event loop.

**c) Auto-recovery on error.** If any SoCo call fails, `_speaker` is set to `None`. The next `play_uri` call triggers rediscovery automatically.

**d) Remove `get_current_track_uri`.** Only used by the server (which has its own `sonos_api.py`). Dead code in the client.

The async public interface:

```python
async def discover(self) -> None       # retry loop until speaker found
async def play_uri(self, uri: str) -> None  # discovers first if needed
async def stop_playback(self) -> None       # no-op if no speaker
```

Internal helpers stay synchronous (they run inside the executor):

```python
def _find_speaker(self) -> SoCo     # single discovery attempt
def _do_play(self, uri: str) -> None  # clear_queue + add + play_from_queue
```

`_do_play` preserves the current share-link vs. direct-URI branching. `stop_playback` still calls `pause()` (not `stop()`), preserving queue position.

### 3. `sync.py` — async wrappers

`poll()` stays synchronous and unchanged. Two methods get async wrappers:

- **`run()`**: becomes `async def run()`. Calls `poll()` via `run_in_executor`, then `asyncio.sleep(10)`. No more `time.sleep` in a thread.
- **`report_unknown_tag()`**: becomes `async def report_unknown_tag()`. Calls `requests.post` via `run_in_executor`. Now usable as a fire-and-forget `create_task`.

### 4. `control.py` — presence events and daemon management

**Remove** `TagReader` protocol, `STOP_COMMAND`, `process_tag()`, `main_loop()`, all debounce logic.

**`PlaybackController`** keeps the same constructor, gets two new async methods replacing `handle_tag`:

- `handle_present(tag_uid)` — look up URI in cache. If found: `await sonos_api.play_uri(uri)`. If unknown: fire-and-forget `create_task(sync.report_unknown_tag(uid))`.
- `handle_removed(tag_uid)` — `await sonos_api.stop_playback()`.

STOP cards are gone. Removing any tag pauses playback.

**`nfc_reader(controller)`** — new async coroutine, replaces `main_loop`. This is the core of the new architecture:

1. Spawn the C daemon via `asyncio.create_subprocess_exec`
2. Read stdout line by line, dispatch `PRESENT`/`REMOVED` to the controller
3. On EOF (daemon died): wait, then restart with exponential backoff
4. On exit/cancellation: terminate the child process

Five important details:

- **Handler errors must not kill the daemon.** Each `handle_present` / `handle_removed` call in the event dispatch loop must be wrapped in its own `try/except`. Without this, a Sonos error in `play_uri` would propagate up, hit the outer `except`, and trigger a daemon restart — even though the daemon is fine and still running.

- **Child cleanup (`try/finally`):** When the coroutine exits (cancellation, exception, `KeyboardInterrupt`), the `finally` block calls `proc.terminate()` with a 3-second timeout, escalating to `proc.kill()`.

- **`PR_SET_PDEATHSIG`:** Passed as `preexec_fn` when spawning the daemon. Tells the kernel to SIGTERM the child when the parent process dies. Safety net for cases where the `finally` block can't run (parent killed with SIGKILL or crashes in C extension). Must be guarded with `sys.platform == "linux"` — loading `libc.so.6` via ctypes would crash on macOS, breaking `make check` on dev machines. Pass `preexec_fn=None` on non-Linux.

```python
if sys.platform == "linux":
    import ctypes
    _libc = ctypes.CDLL("libc.so.6")
    def _set_pdeathsig() -> None:
        _libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
else:
    _set_pdeathsig = None  # used as preexec_fn=_set_pdeathsig (None = no-op)
```

- **Backoff resets after first output, not after spawn.** Prevents tight restart loops when the daemon starts but immediately crashes.

- **Event processing is sequential.** `nfc_reader` awaits each handler before reading the next line. This means a slow `play_uri` (e.g., Spotify share link resolution, 1-5 seconds) delays processing of a subsequent `REMOVED` event. The user removes the tag but music keeps playing for a few seconds until the SoCo call completes. This is an acceptable tradeoff — it avoids all concurrency between play and pause calls on the same speaker.

### 5. `main.py` — async entry point

```
async def main():
    1. Set up logging, create cache/sonos_api/sync/controller
    2. Install SIGTERM handler (cancels all tasks)
    3. Best-effort initial sync (poll once via executor)
    4. Start background tasks: sync.run(), sonos_api.discover()
    5. await nfc_reader(controller)  — runs forever

def run():
    asyncio.run(main())       — handles SIGINT via KeyboardInterrupt
    os._exit(0)               — safety net for stuck executor threads
```

**Why SIGTERM needs explicit handling:** `asyncio.run()` only handles SIGINT (raises `KeyboardInterrupt`). systemd sends SIGTERM to stop services. Without a handler, the C daemon would be orphaned. The handler cancels all tasks, which triggers `CancelledError` in `nfc_reader`, which runs its `finally` block and terminates the daemon.

**Why `os._exit(0)` is still needed:** SoCo and HTTP calls run in executor threads. If one hangs during shutdown, the non-daemon thread prevents process exit. Same reason as the current code, just a different blocking call (SoCo instead of SPI).

### 6. Deletions and config updates

- **Delete `rfid_reader.py` and `read_rfid_tag_id.py`** — RC522-specific, replaced by C daemon
- **`pyproject.toml`**: remove `mfrc522` and `RPi.GPIO` dependencies
- **`config.py`**: add `NFC_DAEMON_PATH` (read from env var, default `/usr/local/bin/nfc-daemon`)
- **`Makefile`**: add `build-nfc-daemon` target, remove `read-tag` target
- **`CLAUDE.md`**: remove RC522 gotchas, add C daemon architecture notes
- **`../Makefile`**: add `build-nfc-daemon` target, update `sync-client` to deploy daemon binary, remove `read-tag` target
- **`.env.sample`**: add `NFC_DAEMON_PATH`
- **`tontraeger-client.service`**: add `Environment="NFC_DAEMON_PATH=/usr/local/bin/nfc-daemon"`

---

## Edge cases and known behaviors

Things the implementer should be aware of that aren't bugs but affect user experience or require care:

| Scenario | What happens | Acceptable? |
|---|---|---|
| Tag removed during slow `play_uri` | Pause is delayed until the SoCo call finishes (1-5s for Spotify) | Yes — avoids concurrent speaker access |
| Daemon restarts while tag is on reader | Tag re-detected as new → playback restarts briefly | Yes — rare, only on daemon crash |
| Two tags placed at the same time | One detected non-deterministically; second found after first removed | Yes — hardware limitation |
| Mapping updated while tag is present | No effect until tag is removed and re-placed | Yes — expected |
| Speaker misconfigured (wrong name) | `discover()` retries forever, logging available names every 5s | Yes — logs help diagnose |
| `play_uri` fails (Sonos error) | Logged, speaker cleared for rediscovery, silence until next tag event | Yes — self-healing |
| Tag removed when nothing is playing | `pause()` on an idle speaker is a no-op | Yes |
| Server has a STOP mapping | Client tries to play "STOP" as a URI → Sonos error → logged, speaker cleared | Yes — STOP cards are obsolete, clean up server-side |

---

## Test plan

### `test_cache.py` — no changes

### `test_sync.py` — minor async additions

Existing `TestPoll` tests stay unchanged (`poll` is still synchronous).

| New/changed test | Verifies |
|---|---|
| `test_report_unknown_tag_posts` | Async wrapper calls `requests.post` via executor |
| `test_report_unknown_tag_error_is_swallowed` | Network error doesn't propagate |
| `test_run_calls_poll_periodically` | `run()` calls poll and sleeps in a loop |

### `test_sonos_api.py` — rewrite for async interface

All tests become `@pytest.mark.asyncio`. The internal synchronous helpers (`_find_speaker`, `_do_play`) are replaced via subclassing (override in a test subclass) rather than `unittest.mock.patch`, keeping with the project's fakes-over-mocks convention. This tests the async wrapping while keeping the SoCo interaction fakeable.

| Test | Verifies |
|---|---|
| `test_init_does_not_discover` | Constructor sets `_speaker = None`, no side effects |
| `test_discover_finds_speaker` | `discover()` sets `_speaker` on success |
| `test_discover_retries_on_failure` | Retries with 5s sleep on discovery error |
| `test_play_uri_native` | Non-https URI uses `add_uri_to_queue` |
| `test_play_uri_share_link` | https URI uses `ShareLinkPlugin` |
| `test_play_discovers_if_no_speaker` | `play_uri` triggers discovery when `_speaker` is None |
| `test_play_error_clears_speaker` | SoCo error sets `_speaker = None` for rediscovery |
| `test_stop_pauses` | Calls `speaker.pause()` |
| `test_stop_no_speaker_is_noop` | Returns immediately when `_speaker` is None |
| `test_stop_error_clears_speaker` | SoCo error sets `_speaker = None` |

### `test_control.py` — rewrite for presence model

`DummySonosAPI` and `DummySync` become async fakes matching the new interfaces.

| Test | Verifies |
|---|---|
| `test_handle_present_plays_uri` | Known tag triggers `play_uri` |
| `test_handle_present_unknown_reports` | Unknown tag fires `report_unknown_tag` task |
| `test_handle_present_unknown_without_sync` | No crash when sync is None |
| `test_handle_removed_pauses` | Tag removal triggers `stop_playback` |
| `test_nfc_reader_dispatches_present` | `PRESENT <uid>` line → `handle_present` called |
| `test_nfc_reader_dispatches_removed` | `REMOVED <uid>` line → `handle_removed` called |
| `test_nfc_reader_restarts_on_eof` | Daemon exit triggers restart with backoff |
| `test_nfc_reader_terminates_child_on_exit` | `proc.terminate()` called in finally |
| `test_nfc_reader_backoff_resets_after_output` | Backoff resets only after first line received |
| `test_nfc_reader_handler_error_continues` | Sonos error in `handle_present` doesn't restart daemon |
| `test_nfc_reader_malformed_line_logged` | Garbage/empty UID lines logged, not crashed |
| `test_nfc_reader_daemon_not_found` | Missing binary triggers backoff, not crash |

---

## Implementation order

Each phase should pass `make check` before starting the next.

| Phase | Steps | What changes |
|---|---|---|
| **1. C daemon** | Write `nfc-daemon/main.c` + `nfc-daemon/Makefile`, add build target to `Makefile` | Testable independently on Pi with PN532 |
| **2. Async Sonos** | Rework `sonos_api.py`, rewrite `test_sonos_api.py` | No other module depends on the old interface yet |
| **3. Async sync** | Update `sync.py`, update `test_sync.py` | `poll()` unchanged, only `run` and `report_unknown_tag` change |
| **4. Control layer** | Rewrite `control.py`, rewrite `test_control.py` | New presence model, `nfc_reader` coroutine |
| **5. Wire up** | Rewrite `main.py`, delete `rfid_reader.py` + `read_rfid_tag_id.py`, update `pyproject.toml`, update `config.py`, update `CLAUDE.md` | Everything connected |
| **6. Deploy** | Update `../Makefile`, `Makefile`, `tontraeger-client.service`, `.env.sample` | Ready to ship |
