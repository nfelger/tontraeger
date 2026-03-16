import json
import logging
import os
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


class MappingCache:
    """In-memory tag-to-URI cache backed by a JSON file on disk.

    The JSON file stores a list of mapping objects:
        [{"tag_uid": "...", "media_uri": "...", "name": "...", "shuffle": false}, ...]

    The in-memory representation is a dict keyed by tag_uid for O(1) lookup.
    """

    def __init__(self, cache_path: str) -> None:
        self._cache_path = cache_path
        self._mappings: dict[str, tuple[str, str, bool]] = {}  # tag_uid -> (media_uri, name, shuffle)
        self._load()

    @staticmethod
    def _parse(mappings: list[dict]) -> dict[str, tuple[str, str, bool]]:
        return {
            m["tag_uid"]: (m["media_uri"], m.get("name", ""), bool(m["shuffle"]))
            for m in mappings
        }

    def _load(self) -> None:
        """Load mappings from the JSON file on disk, if it exists.

        A corrupt or unreadable file is logged and treated as empty — the next
        successful server sync will repopulate it.
        """
        if not os.path.exists(self._cache_path):
            return
        try:
            with open(self._cache_path, "r") as f:
                data = json.load(f)
            self._mappings = self._parse(data)
        except (json.JSONDecodeError, KeyError, TypeError, OSError) as e:
            logger.warning("Corrupt cache file %s, starting empty: %s", self._cache_path, e)

    def get_uri(self, tag_uid: str) -> Optional[str]:
        """Return the media URI for a tag, or None if not cached."""
        entry = self._mappings.get(tag_uid)
        if entry is None:
            return None
        return entry[0]

    def get_name(self, tag_uid: str) -> Optional[str]:
        """Return the name for a tag, or None if not cached."""
        entry = self._mappings.get(tag_uid)
        if entry is None:
            return None
        return entry[1]

    def get_shuffle(self, tag_uid: str) -> bool:
        """Return whether shuffle is enabled for a tag. Returns False if not cached."""
        entry = self._mappings.get(tag_uid)
        if entry is None:
            return False
        return entry[2]

    def update(self, mappings: list[dict]) -> None:
        """Replace all cached mappings and persist to disk atomically."""
        self._mappings = self._parse(mappings)
        self._persist()

    def all_mappings(self) -> dict[str, tuple[str, str, bool]]:
        """Return all cached mappings as {tag_uid: (media_uri, name, shuffle)}."""
        return dict(self._mappings)

    def _persist(self) -> None:
        """Write mappings to disk atomically (write to temp file, then rename)."""
        data = [
            {"tag_uid": uid, "media_uri": uri, "name": name, "shuffle": shuffle}
            for uid, (uri, name, shuffle) in self._mappings.items()
        ]
        dir_name = os.path.dirname(self._cache_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._cache_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
