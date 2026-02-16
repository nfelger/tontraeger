import hashlib
import json
import sqlite3
from typing import Optional

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
                    name TEXT NOT NULL DEFAULT ''
                )
                """
            )
            try:
                cursor.execute("ALTER TABLE tags ADD COLUMN name TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            conn.commit()
        finally:
            conn.close()

    def insert_mapping(self, tag_uid: str, media_uri: str, name: str = "") -> None:
        """Inserts or updates a mapping between a tag UID and a media URI."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO tags (tag_uid, media_uri, name)
                VALUES (?, ?, ?)
                """,
                (tag_uid, media_uri, name),
            )
            conn.commit()
        finally:
            conn.close()

    def get_all_mappings(self) -> list[tuple[str, str, str]]:
        """Returns all (tag_uid, media_uri, name) mappings."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT tag_uid, media_uri, name FROM tags ORDER BY tag_uid")
            return cursor.fetchall()
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

    def get_uri(self, tag_uid: str) -> Optional[str]:
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

    def content_hash(self) -> str:
        """SHA-256 of all mappings, for use as ETag."""
        mappings = self.get_all_mappings()
        serialized = json.dumps(
            [{"tag_uid": t, "media_uri": u, "name": n} for t, u, n in mappings],
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode()).hexdigest()
