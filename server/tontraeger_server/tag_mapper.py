import hashlib
import json
import sqlite3
from typing import NamedTuple

DATABASE_FILE = "tags.db"


class Mapping(NamedTuple):
    id: int
    tag_uid: str | None
    media_uri: str
    name: str
    shuffle: bool
    has_image: bool


class TagMapper:
    def __init__(self, db_path: str = DATABASE_FILE) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initializes the database schema, running migrations as needed."""
        conn = sqlite3.connect(self.db_path, isolation_level=None)  # autocommit mode
        try:
            cursor = conn.cursor()

            # ADD COLUMN guards for old databases that predate those columns.
            # Only run if the table already exists; run before migration so the
            # recreation copies all columns correctly.
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tags'")
            if cursor.fetchone():
                try:
                    cursor.execute("ALTER TABLE tags ADD COLUMN shuffle INTEGER NOT NULL DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
                try:
                    cursor.execute("ALTER TABLE tags ADD COLUMN image_data TEXT NOT NULL DEFAULT ''")
                except sqlite3.OperationalError:
                    pass

            # Detect current schema state via column names.
            cursor.execute("PRAGMA table_info(tags)")
            cols = {row[1] for row in cursor.fetchall()}

            if not cols:
                # Fresh database — create with new schema directly.
                cursor.execute(
                    """
                    CREATE TABLE tags (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tag_uid TEXT UNIQUE,
                        media_uri TEXT NOT NULL,
                        name TEXT NOT NULL DEFAULT '',
                        shuffle INTEGER NOT NULL DEFAULT 0,
                        image_data TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
            elif "id" not in cols:
                # Old schema with tag_uid as PK — recreate with surrogate PK.
                # Explicit transaction makes the entire 4-step recreation atomic:
                # if the process crashes mid-way, SQLite rolls back and the migration
                # re-runs cleanly on next startup.
                cursor.execute("BEGIN IMMEDIATE")
                cursor.execute("DROP TABLE IF EXISTS tags_new")  # cleanup from any prior partial run
                cursor.execute(
                    """
                    CREATE TABLE tags_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tag_uid TEXT UNIQUE,
                        media_uri TEXT NOT NULL,
                        name TEXT NOT NULL DEFAULT '',
                        shuffle INTEGER NOT NULL DEFAULT 0,
                        image_data TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO tags_new (tag_uid, media_uri, name, shuffle, image_data)
                    SELECT tag_uid, media_uri, name, shuffle, image_data
                    FROM tags ORDER BY tag_uid
                    """
                )
                cursor.execute("DROP TABLE tags")
                cursor.execute("ALTER TABLE tags_new RENAME TO tags")
                cursor.execute("COMMIT")
        finally:
            conn.close()

    def create_mapping(
        self,
        media_uri: str,
        name: str = "",
        shuffle: bool = False,
        tag_uid: str | None = None,
    ) -> int:
        """Inserts a new mapping. Returns the new row's integer id."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO tags (tag_uid, media_uri, name, shuffle) VALUES (?, ?, ?, ?)",
                (tag_uid, media_uri, name, int(shuffle)),
            )
            conn.commit()
            if cursor.lastrowid is None:
                raise RuntimeError("INSERT did not return a row id")
            return cursor.lastrowid
        finally:
            conn.close()

    def update_mapping(
        self,
        mapping_id: int,
        media_uri: str,
        name: str = "",
        shuffle: bool = False,
        tag_uid: str | None = None,
    ) -> None:
        """Updates an existing mapping by id. Raises IntegrityError on duplicate tag_uid."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tags SET tag_uid = ?, media_uri = ?, name = ?, shuffle = ? WHERE id = ?",
                (tag_uid, media_uri, name, int(shuffle), mapping_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_mapping(self, mapping_id: int) -> Mapping | None:
        """Returns a Mapping for the given id, or None."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, tag_uid, media_uri, name, shuffle, image_data != '' FROM tags WHERE id = ?",
                (mapping_id,),
            )
            row = cursor.fetchone()
            if row:
                return Mapping(row[0], row[1], row[2], row[3], bool(row[4]), bool(row[5]))
            return None
        finally:
            conn.close()

    def get_all_mappings(self) -> list[Mapping]:
        """Returns all Mapping objects ordered by id."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, tag_uid, media_uri, name, shuffle, image_data != '' FROM tags ORDER BY id"
            )
            return [Mapping(i, t, u, n, bool(s), bool(hi)) for i, t, u, n, s, hi in cursor.fetchall()]
        finally:
            conn.close()

    def get_mappings_with_images(self, ids: list[int]) -> list[tuple[int, str]]:
        """Returns (id, image_data) for the given ids that have images."""
        if not ids:
            return []
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in ids)
            cursor.execute(
                f"SELECT id, image_data FROM tags WHERE id IN ({placeholders}) AND image_data != ''",
                ids,
            )
            return cursor.fetchall()
        finally:
            conn.close()

    def upsert_image(self, mapping_id: int, image_data: str) -> bool:
        """Stores base64-encoded image data for a mapping. Returns True if the mapping exists."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tags SET image_data = ? WHERE id = ?",
                (image_data, mapping_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_mapping(self, mapping_id: int) -> None:
        """Deletes the mapping with the given id."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tags WHERE id = ?", (mapping_id,))
            conn.commit()
        finally:
            conn.close()

    def get_uri(self, tag_uid: str) -> str | None:
        """Returns the media URI associated with the given tag UID, or None."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT media_uri FROM tags WHERE tag_uid = ?", (tag_uid,))
            row = cursor.fetchone()
            if row:
                return row[0]
            return None
        finally:
            conn.close()

    def compute_hash(self, mappings: list[Mapping]) -> str:
        """SHA-256 of the given mappings, for use as ETag. Excludes id and image data.

        Sorts by tag_uid for determinism regardless of input order.
        Caller is responsible for filtering out mappings with null tag_uid.
        """
        entries = sorted(
            [{"tag_uid": m.tag_uid, "media_uri": m.media_uri, "name": m.name, "shuffle": m.shuffle} for m in mappings],
            key=lambda x: x["tag_uid"] or "",
        )
        serialized = json.dumps(entries, sort_keys=True)
        return hashlib.sha256(serialized.encode()).hexdigest()

    def content_hash(self) -> str:
        """SHA-256 of all assigned (non-null tag_uid) mappings, for use as ETag."""
        mappings = [m for m in self.get_all_mappings() if m.tag_uid is not None]
        return self.compute_hash(mappings)
