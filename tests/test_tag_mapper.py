import os
import tempfile
import pytest
from spotibox.tag_mapper import TagMapper

@pytest.fixture
def temp_db() -> str:
    """
    Creates a temporary database file and returns its path.
    Cleans up after the test is done.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.remove(path)

def test_insert_and_get_mapping(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    test_tag = "1234567890"
    test_uri = "x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0"
    mapper.insert_mapping(test_tag, test_uri)

    retrieved_uri = mapper.get_uri(test_tag)
    assert retrieved_uri == test_uri

def test_get_nonexistent_mapping(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    retrieved_uri = mapper.get_uri("nonexistent_tag")
    assert retrieved_uri is None
