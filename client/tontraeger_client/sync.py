import logging
import time

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

        data = resp.json()
        self._cache.update(data.get("mappings", []))
        return True

    def report_unknown_tag(self, tag_uid: str) -> None:
        """POST /api/unknown-tags. Fire-and-forget (log errors, don't crash)."""
        url = f"{self._server_url}/api/unknown-tags"
        try:
            requests.post(url, json={"tag_uid": tag_uid}, timeout=5)
        except requests.RequestException as e:
            logger.warning("Failed to report unknown tag %s: %s", tag_uid, e)

    def run(self, interval: float = 10.0) -> None:
        """Blocking loop: poll every `interval` seconds. Runs forever."""
        while True:
            self.poll()
            time.sleep(interval)
