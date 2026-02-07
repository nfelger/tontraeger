import os
import tempfile
import pytest
from spotibox.playlist_mapper import PlaylistMapper

@pytest.fixture
def temp_db() -> str:
    """
    Creates a temporary database file and returns its path.
    Cleans up after the test is done.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)  # Close the file descriptor.
    yield path
    os.remove(path)

def test_insert_and_get_mapping(temp_db: str) -> None:
    mapper = PlaylistMapper(db_path=temp_db)
    test_tag = "1234567890"
    test_uri = "spotify:playlist:TESTURI"
    mapper.insert_mapping(test_tag, test_uri)

    retrieved_uri = mapper.get_playlist_uri(test_tag)
    assert retrieved_uri == test_uri

def test_get_nonexistent_mapping(temp_db: str) -> None:
    mapper = PlaylistMapper(db_path=temp_db)
    retrieved_uri = mapper.get_playlist_uri("nonexistent_tag")
    assert retrieved_uri is None
