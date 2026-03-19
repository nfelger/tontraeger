import os
import tempfile
import pytest
from tontraeger_server.tag_mapper import TagMapper

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
    mapper.insert_mapping(test_tag, test_uri, name="Jazz Radio")

    retrieved_uri = mapper.get_uri(test_tag)
    assert retrieved_uri == test_uri

def test_get_nonexistent_mapping(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    retrieved_uri = mapper.get_uri("nonexistent_tag")
    assert retrieved_uri is None


def test_get_all_mappings(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.insert_mapping("aaa", "uri_a", "Alpha")
    mapper.insert_mapping("bbb", "uri_b")
    mapper.insert_mapping("ccc", "uri_c", "Charlie")

    mappings = mapper.get_all_mappings()
    assert mappings == [
        ("aaa", "uri_a", "Alpha", False, False),
        ("bbb", "uri_b", "", False, False),
        ("ccc", "uri_c", "Charlie", False, False),
    ]


def test_get_all_mappings_empty(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    assert mapper.get_all_mappings() == []


def test_get_all_mappings_has_image_flag(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.insert_mapping("aaa", "uri_a", "Alpha")
    mapper.upsert_image("aaa", "iVBORw0KGgo=")

    mappings = mapper.get_all_mappings()
    assert mappings[0] == ("aaa", "uri_a", "Alpha", False, True)


def test_upsert_image(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.insert_mapping("aaa", "uri_a")
    assert mapper.upsert_image("aaa", "base64data") is True

    rows = mapper.get_mappings_with_images(["aaa"])
    assert len(rows) == 1
    assert rows[0] == ("aaa", "base64data")


def test_upsert_image_nonexistent_tag(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    assert mapper.upsert_image("missing", "data") is False


def test_insert_mapping_preserves_image_data(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.insert_mapping("aaa", "uri_a", "Alpha")
    mapper.upsert_image("aaa", "img_data")

    # Re-saving the mapping should preserve image_data
    mapper.insert_mapping("aaa", "uri_b", "Alpha Updated", shuffle=True)

    rows = mapper.get_mappings_with_images(["aaa"])
    assert len(rows) == 1
    assert rows[0][1] == "img_data"
    # Verify other fields were updated
    mappings = mapper.get_all_mappings()
    assert mappings[0] == ("aaa", "uri_b", "Alpha Updated", True, True)


def test_upsert_image_overwrites(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.insert_mapping("aaa", "uri_a")
    mapper.upsert_image("aaa", "old")
    mapper.upsert_image("aaa", "new")

    rows = mapper.get_mappings_with_images(["aaa"])
    assert rows[0][1] == "new"


def test_get_mappings_with_images(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.insert_mapping("aaa", "uri_a")
    mapper.insert_mapping("bbb", "uri_b")
    mapper.insert_mapping("ccc", "uri_c")
    mapper.upsert_image("aaa", "img_a")
    mapper.upsert_image("ccc", "img_c")

    rows = mapper.get_mappings_with_images(["aaa", "bbb", "ccc"])
    assert len(rows) == 2
    assert ("aaa", "img_a") in rows
    assert ("ccc", "img_c") in rows


def test_get_mappings_with_images_empty_uids(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    assert mapper.get_mappings_with_images([]) == []


def test_delete_mapping(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.insert_mapping("tag1", "uri1")
    mapper.insert_mapping("tag2", "uri2")

    mapper.delete_mapping("tag1")

    assert mapper.get_uri("tag1") is None
    assert mapper.get_uri("tag2") == "uri2"


def test_delete_nonexistent_mapping(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.delete_mapping("does_not_exist")  # should not raise


def test_content_hash_empty(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    h = mapper.content_hash()
    assert isinstance(h, str)
    assert len(h) == 64


def test_content_hash_deterministic(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.insert_mapping("aaa", "uri_a", "Alpha")
    mapper.insert_mapping("bbb", "uri_b")
    assert mapper.content_hash() == mapper.content_hash()


def test_content_hash_changes_on_insert(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    h1 = mapper.content_hash()
    mapper.insert_mapping("aaa", "uri_a")
    h2 = mapper.content_hash()
    assert h1 != h2


def test_content_hash_changes_on_delete(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.insert_mapping("aaa", "uri_a")
    h1 = mapper.content_hash()
    mapper.delete_mapping("aaa")
    h2 = mapper.content_hash()
    assert h1 != h2


def test_content_hash_changes_on_update(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.insert_mapping("aaa", "uri_a")
    h1 = mapper.content_hash()
    mapper.insert_mapping("aaa", "uri_b")
    h2 = mapper.content_hash()
    assert h1 != h2


def test_content_hash_independent_of_insertion_order(temp_db: str) -> None:
    mapper1 = TagMapper(db_path=temp_db)
    mapper1.insert_mapping("bbb", "uri_b")
    mapper1.insert_mapping("aaa", "uri_a")
    h1 = mapper1.content_hash()

    fd2, path2 = tempfile.mkstemp(suffix=".db")
    os.close(fd2)
    mapper2 = TagMapper(db_path=path2)
    mapper2.insert_mapping("aaa", "uri_a")
    mapper2.insert_mapping("bbb", "uri_b")
    h2 = mapper2.content_hash()
    os.remove(path2)

    assert h1 == h2
