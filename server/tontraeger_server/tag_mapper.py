import hashlib
import json
import sqlite3

DATABASE_FILE = "tags.db"

class TagMapper:
    def __init__(self, db_path: str = DATABASE_FILE) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initializes the SQLite database and creates the tags table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tags (
                    tag_uid TEXT PRIMARY KEY,
                    media_uri TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    shuffle INTEGER NOT NULL DEFAULT 0,
                    image_data TEXT NOT NULL DEFAULT ''
                )
                """
            )
            try:
                cursor.execute("ALTER TABLE tags ADD COLUMN shuffle INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            try:
                cursor.execute("ALTER TABLE tags ADD COLUMN image_data TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            conn.commit()
        finally:
            conn.close()

    def insert_mapping(self, tag_uid: str, media_uri: str, name: str = "", shuffle: bool = False) -> None:
        """Inserts or updates a mapping between a tag UID and a media URI."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO tags (tag_uid, media_uri, name, shuffle)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tag_uid) DO UPDATE SET
                    media_uri = excluded.media_uri,
                    name = excluded.name,
                    shuffle = excluded.shuffle
                """,
                (tag_uid, media_uri, name, int(shuffle)),
            )
            conn.commit()
        finally:
            conn.close()

    def get_all_mappings(self) -> list[tuple[str, str, str, bool, bool]]:
        """Returns all (tag_uid, media_uri, name, shuffle, has_image) mappings."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT tag_uid, media_uri, name, shuffle, image_data != '' FROM tags ORDER BY tag_uid"
            )
            return [(t, u, n, bool(s), bool(hi)) for t, u, n, s, hi in cursor.fetchall()]
        finally:
            conn.close()

    def get_mappings_with_images(self, uids: list[str]) -> list[tuple[str, str]]:
        """Returns (tag_uid, image_data) for the given UIDs that have images."""
        if not uids:
            return []
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            placeholders = ",".join("?" for _ in uids)
            cursor.execute(
                f"SELECT tag_uid, image_data FROM tags WHERE tag_uid IN ({placeholders}) AND image_data != ''",
                uids,
            )
            return cursor.fetchall()
        finally:
            conn.close()

    def upsert_image(self, tag_uid: str, image_data: str) -> bool:
        """Stores base64-encoded image data for a mapping. Returns True if the mapping exists."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tags SET image_data = ? WHERE tag_uid = ?",
                (image_data, tag_uid),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_mapping(self, tag_uid: str) -> None:
        """Deletes the mapping for the given tag UID."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tags WHERE tag_uid = ?", (tag_uid,))
            conn.commit()
        finally:
            conn.close()

    def get_uri(self, tag_uid: str) -> str | None:
        """
        Retrieves the media URI (or special command) associated with the given tag UID.
        Returns None if no mapping exists.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT media_uri FROM tags WHERE tag_uid = ?",
                (tag_uid,),
            )
            row = cursor.fetchone()
            if row:
                return row[0]
            return None
        finally:
            conn.close()

    def compute_hash(self, mappings: list[tuple[str, str, str, bool, bool]]) -> str:
        """SHA-256 of the given mappings, for use as ETag. Excludes image data."""
        serialized = json.dumps(
            [{"tag_uid": t, "media_uri": u, "name": n, "shuffle": s} for t, u, n, s, _hi in mappings],
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode()).hexdigest()

    def content_hash(self) -> str:
        """SHA-256 of all mappings, for use as ETag. Excludes image data."""
        return self.compute_hash(self.get_all_mappings())
