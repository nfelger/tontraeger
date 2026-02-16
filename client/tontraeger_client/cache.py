import json
import os
import tempfile
from typing import Optional


class MappingCache:
    """In-memory tag-to-URI cache backed by a JSON file on disk.

    The JSON file stores a list of mapping objects:
        [{"tag_uid": "...", "media_uri": "...", "name": "..."}, ...]

    The in-memory representation is a dict keyed by tag_uid for O(1) lookup.
    """

    def __init__(self, cache_path: str) -> None:
        self._cache_path = cache_path
        self._mappings: dict[str, tuple[str, str]] = {}  # tag_uid -> (media_uri, name)
        self._load()

    def _load(self) -> None:
        """Load mappings from the JSON file on disk, if it exists."""
        if not os.path.exists(self._cache_path):
            return
        with open(self._cache_path, "r") as f:
            data = json.load(f)
        self._mappings = {
            m["tag_uid"]: (m["media_uri"], m.get("name", ""))
            for m in data
        }

    def get_uri(self, tag_uid: str) -> Optional[str]:
        """Return the media URI for a tag, or None if not cached."""
        entry = self._mappings.get(tag_uid)
        if entry is None:
            return None
        return entry[0]

    def update(self, mappings: list[dict]) -> None:
        """Replace all cached mappings and persist to disk atomically."""
        self._mappings = {
            m["tag_uid"]: (m["media_uri"], m.get("name", ""))
            for m in mappings
        }
        self._persist()

    def all_mappings(self) -> dict[str, tuple[str, str]]:
        """Return all cached mappings as {tag_uid: (media_uri, name)}."""
        return dict(self._mappings)

    def _persist(self) -> None:
        """Write mappings to disk atomically (write to temp file, then rename)."""
        data = [
            {"tag_uid": uid, "media_uri": uri, "name": name}
            for uid, (uri, name) in self._mappings.items()
        ]
        dir_name = os.path.dirname(self._cache_path) or "."
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp_path, self._cache_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
