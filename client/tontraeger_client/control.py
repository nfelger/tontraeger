import asyncio
import logging
import signal
import sys

from tontraeger_client.cache import MappingCache
from tontraeger_client.sonos_api import SonosAPI
from tontraeger_client.sync import MappingSync

logger = logging.getLogger(__name__)

# Tell Linux to kill the NFC daemon child process if the parent (Python) dies.
# Without this, a hard crash would leave the daemon running as an orphan.
# Linux-only: the ctypes call would crash on macOS, breaking tests.
if sys.platform == "linux":
    import ctypes

    _libc = ctypes.CDLL("libc.so.6")
    _PR_SET_PDEATHSIG = 1

    def _set_pdeathsig() -> None:
        _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)
else:
    _set_pdeathsig = None


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

    async def handle_present(self, tag_uid: str) -> None:
        """A tag was placed on the reader. Play its music, or report it as unknown."""
        uri = self.cache.get_uri(tag_uid)
        if uri is None:
            logger.info("Unknown tag: %s", tag_uid)
            if self.sync is not None:
                # Fire-and-forget: report_unknown_tag has its own error handling.
                # Store a reference so the task isn't garbage-collected mid-execution.
                self._pending_report = asyncio.create_task(self.sync.report_unknown_tag(tag_uid))
            return
        name = self.cache.get_name(tag_uid) or tag_uid
        logger.info("Playing %s (%s)", name, uri)
        await self.sonos_api.play_uri(uri)

    async def handle_removed(self, tag_uid: str) -> None:
        """A tag was removed from the reader. Pause playback."""
        name = self.cache.get_name(tag_uid) or tag_uid
        logger.info("Pausing (%s removed)", name)
        await self.sonos_api.stop_playback()


async def nfc_reader(controller: PlaybackController, daemon_path: str) -> None:
    """Run the NFC daemon and react to tag events. Runs forever.

    Reads PRESENT/REMOVED lines from the daemon's stdout and calls
    the controller. If the daemon crashes, restarts it with increasing
    delays (1s, 2s, 4s, ... up to 30s). The delay resets after the daemon
    produces its first output (i.e., it actually started working).
    """
    backoff_s = 1.0
    max_backoff_s = 30.0

    while True:
        proc: asyncio.subprocess.Process | None = None
        try:
            proc = await asyncio.create_subprocess_exec(
                daemon_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=None,  # inherit — flows to journald
                preexec_fn=_set_pdeathsig,
            )
            logger.info("NFC daemon started (pid %s)", proc.pid)

            assert proc.stdout is not None
            first_line = True

            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break  # EOF — daemon died

                if first_line:
                    backoff_s = 1.0  # reset after first output
                    first_line = False

                line = line_bytes.decode(errors="replace").strip()
                if not line:
                    continue

                parts = line.split(" ", 1)
                if len(parts) != 2 or parts[0] not in ("PRESENT", "REMOVED"):
                    logger.warning("Malformed daemon output: %r", line)
                    continue

                event, tag_uid = parts
                if not tag_uid:
                    logger.warning("Empty UID in daemon output: %r", line)
                    continue

                try:
                    if event == "PRESENT":
                        await controller.handle_present(tag_uid)
                    else:
                        await controller.handle_removed(tag_uid)
                except Exception:
                    logger.exception("Error handling %s event for tag %s", event, tag_uid)

            # Daemon exited
            returncode = await proc.wait()
            logger.warning(
                "NFC daemon exited (code %s), restarting in %.0fs", returncode, backoff_s
            )

        except FileNotFoundError:
            logger.error(
                "NFC daemon binary not found: %s — retrying in %.0fs", daemon_path, backoff_s
            )

        except asyncio.CancelledError:
            raise  # let finally handle cleanup

        except Exception:
            logger.exception("Unexpected error in nfc_reader, restarting in %.0fs", backoff_s)

        finally:
            # Clean up the daemon process if it's still running.
            # shield() prevents task cancellation from interrupting the wait.
            if proc is not None and proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=3.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    proc.kill()
                    try:
                        await asyncio.shield(proc.wait())
                    except asyncio.CancelledError:
                        pass
                logger.info("NFC daemon terminated")

        await asyncio.sleep(backoff_s)
        backoff_s = min(backoff_s * 2, max_backoff_s)
