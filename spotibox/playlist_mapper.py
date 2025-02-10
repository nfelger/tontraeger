# spotibox/playlist_mapper.py

import sqlite3
from typing import Optional

# Default database file (placed in the project root; adjust as needed)
DATABASE_FILE = "playlists.db"

class PlaylistMapper:
    def __init__(self, db_path: str = DATABASE_FILE) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initializes the SQLite database and creates the playlists table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS playlists (
                    tag_uid TEXT PRIMARY KEY,
                    playlist_uri TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def insert_mapping(self, tag_uid: str, playlist_uri: str) -> None:
        """
        Inserts or updates a mapping between the tag UID and the playlist URI.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO playlists (tag_uid, playlist_uri)
                VALUES (?, ?)
                """,
                (tag_uid, playlist_uri),
            )
            conn.commit()
        finally:
            conn.close()

    def get_playlist_uri(self, tag_uid: str) -> Optional[str]:
        """
        Retrieves the playlist URI associated with the given tag UID.
        Returns None if no mapping exists.
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT playlist_uri FROM playlists WHERE tag_uid = ?",
                (tag_uid,),
            )
            row = cursor.fetchone()
            if row:
                return row[0]
            return None
        finally:
            conn.close()
