import asyncio
import logging

import requests

from tontraeger_client.cache import MappingCache

logger = logging.getLogger(__name__)


class MappingSync:
    """Polls the server for mapping updates and reports unknown tags."""

    def __init__(self, server_url: str, cache: MappingCache) -> None:
        self._server_url = server_url.rstrip("/")
        self._cache = cache
        self._etag: str | None = None

    def poll(self) -> bool:
        """Single poll cycle: GET /api/mappings with If-None-Match.

        Returns True if the cache was updated, False otherwise.
        Handles connection errors gracefully (logs and returns False).
        """
        url = f"{self._server_url}/api/mappings"
        headers: dict[str, str] = {}
        if self._etag is not None:
            headers["If-None-Match"] = self._etag

        try:
            resp = requests.get(url, headers=headers, timeout=10)
        except requests.RequestException as e:
            logger.warning("Failed to poll server: %s", e)
            return False

        if resp.status_code == 304:
            return False

        if resp.status_code != 200:
            logger.warning("Unexpected status from server: %s", resp.status_code)
            return False

        etag = resp.headers.get("ETag")
        if etag:
            self._etag = etag

        try:
            data = resp.json()
        except ValueError:
            logger.warning("Invalid JSON in server response")
            return False
        self._cache.update(data.get("mappings", []))
        return True

    async def report_unknown_tag(self, tag_uid: str) -> None:
        """Tell the server about an unrecognized tag. Errors are logged, not raised."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._post_unknown_tag, tag_uid)
        except Exception as e:
            logger.warning("Failed to report unknown tag %s: %s", tag_uid, e)

    def _post_unknown_tag(self, tag_uid: str) -> None:
        """POST /api/unknown-tags. Blocking (network I/O)."""
        url = f"{self._server_url}/api/unknown-tags"
        resp = requests.post(url, json={"tag_uid": tag_uid}, timeout=5)
        if resp.status_code >= 400:
            logger.warning("Server rejected unknown tag report: %s", resp.status_code)

    async def run(self, interval: float = 10.0) -> None:
        """Poll the server for mapping updates in a loop. Runs forever."""
        loop = asyncio.get_running_loop()
        while True:
            await loop.run_in_executor(None, self.poll)
            await asyncio.sleep(interval)
