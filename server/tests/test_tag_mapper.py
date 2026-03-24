import os
import sqlite3
import tempfile
import pytest
from tontraeger_server.tag_mapper import TagMapper


@pytest.fixture
def temp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.remove(path)


# ---------------------------------------------------------------------------
# get_uri (unchanged — runtime playback lookup)
# ---------------------------------------------------------------------------

def test_get_uri(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.create_mapping("x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0", "Jazz Radio", tag_uid="1234567890")
    assert mapper.get_uri("1234567890") == "x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0"


def test_get_uri_nonexistent(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    assert mapper.get_uri("nonexistent_tag") is None


# ---------------------------------------------------------------------------
# get_all_mappings
# ---------------------------------------------------------------------------

def test_get_all_mappings(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id1 = mapper.create_mapping("uri_a", "Alpha", tag_uid="aaa")
    id2 = mapper.create_mapping("uri_b", tag_uid="bbb")
    id3 = mapper.create_mapping("uri_c", "Charlie", tag_uid="ccc")

    mappings = mapper.get_all_mappings()
    assert mappings == [
        (id1, "aaa", "uri_a", "Alpha", False, False),
        (id2, "bbb", "uri_b", "", False, False),
        (id3, "ccc", "uri_c", "Charlie", False, False),
    ]


def test_get_all_mappings_empty(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    assert mapper.get_all_mappings() == []


def test_get_all_mappings_has_image_flag(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a", "Alpha", tag_uid="aaa")
    mapper.upsert_image(id_, "iVBORw0KGgo=")

    mappings = mapper.get_all_mappings()
    assert mappings[0] == (id_, "aaa", "uri_a", "Alpha", False, True)


# ---------------------------------------------------------------------------
# upsert_image
# ---------------------------------------------------------------------------

def test_upsert_image(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a")
    assert mapper.upsert_image(id_, "base64data") is True

    rows = mapper.get_mappings_with_images([id_])
    assert len(rows) == 1
    assert rows[0] == (id_, "base64data")


def test_upsert_image_nonexistent_tag(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    assert mapper.upsert_image(999, "data") is False


def test_update_mapping_preserves_image_data(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a", "Alpha", tag_uid="aaa")
    mapper.upsert_image(id_, "img_data")

    # Updating the mapping should preserve image_data
    mapper.update_mapping(id_, "uri_b", "Alpha Updated", shuffle=True, tag_uid="aaa")

    rows = mapper.get_mappings_with_images([id_])
    assert len(rows) == 1
    assert rows[0][1] == "img_data"
    # Verify other fields were updated
    m = mapper.get_mapping(id_)
    assert m is not None
    assert m == (id_, "aaa", "uri_b", "Alpha Updated", True, True)


def test_upsert_image_overwrites(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a")
    mapper.upsert_image(id_, "old")
    mapper.upsert_image(id_, "new")

    rows = mapper.get_mappings_with_images([id_])
    assert rows[0][1] == "new"


# ---------------------------------------------------------------------------
# get_mappings_with_images
# ---------------------------------------------------------------------------

def test_get_mappings_with_images(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id1 = mapper.create_mapping("uri_a")
    id2 = mapper.create_mapping("uri_b")
    id3 = mapper.create_mapping("uri_c")
    mapper.upsert_image(id1, "img_a")
    mapper.upsert_image(id3, "img_c")

    rows = mapper.get_mappings_with_images([id1, id2, id3])
    assert len(rows) == 2
    assert (id1, "img_a") in rows
    assert (id3, "img_c") in rows


def test_get_mappings_with_images_empty_uids(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    assert mapper.get_mappings_with_images([]) == []


# ---------------------------------------------------------------------------
# delete_mapping
# ---------------------------------------------------------------------------

def test_delete_mapping(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id1 = mapper.create_mapping("uri1", tag_uid="tag1")
    mapper.create_mapping("uri2", tag_uid="tag2")

    mapper.delete_mapping(id1)

    assert mapper.get_uri("tag1") is None
    assert mapper.get_uri("tag2") == "uri2"


def test_delete_nonexistent_mapping(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.delete_mapping(999)  # should not raise


# ---------------------------------------------------------------------------
# content_hash / compute_hash
# ---------------------------------------------------------------------------

def test_content_hash_empty(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    h = mapper.content_hash()
    assert isinstance(h, str)
    assert len(h) == 64


def test_content_hash_deterministic(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.create_mapping("uri_a", "Alpha", tag_uid="aaa")
    mapper.create_mapping("uri_b", tag_uid="bbb")
    assert mapper.content_hash() == mapper.content_hash()


def test_content_hash_changes_on_insert(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    h1 = mapper.content_hash()
    mapper.create_mapping("uri_a", tag_uid="aaa")
    h2 = mapper.content_hash()
    assert h1 != h2


def test_content_hash_changes_on_delete(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a", tag_uid="aaa")
    h1 = mapper.content_hash()
    mapper.delete_mapping(id_)
    h2 = mapper.content_hash()
    assert h1 != h2


def test_content_hash_changes_on_update(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a", tag_uid="aaa")
    h1 = mapper.content_hash()
    mapper.update_mapping(id_, "uri_b", tag_uid="aaa")
    h2 = mapper.content_hash()
    assert h1 != h2


def test_content_hash_independent_of_insertion_order(temp_db: str) -> None:
    mapper1 = TagMapper(db_path=temp_db)
    mapper1.create_mapping("uri_b", tag_uid="bbb")
    mapper1.create_mapping("uri_a", tag_uid="aaa")
    h1 = mapper1.content_hash()

    fd2, path2 = tempfile.mkstemp(suffix=".db")
    os.close(fd2)
    mapper2 = TagMapper(db_path=path2)
    mapper2.create_mapping("uri_a", tag_uid="aaa")
    mapper2.create_mapping("uri_b", tag_uid="bbb")
    h2 = mapper2.content_hash()
    os.remove(path2)

    assert h1 == h2


def test_content_hash_unaffected_by_unassigned_mapping(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.create_mapping("uri_a", tag_uid="aaa")
    h1 = mapper.content_hash()
    # Adding a mapping without a UID should not change the hash
    mapper.create_mapping("uri_b")
    h2 = mapper.content_hash()
    assert h1 == h2


# ---------------------------------------------------------------------------
# New API: surrogate integer PKs
# ---------------------------------------------------------------------------

def test_create_mapping_returns_id(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a", "Alpha")
    assert isinstance(id_, int)
    assert id_ > 0


def test_create_mapping_without_uid(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a", "Alpha")
    m = mapper.get_mapping(id_)
    assert m is not None
    assert m[0] == id_
    assert m[1] is None
    assert m[2] == "uri_a"
    assert m[3] == "Alpha"


def test_create_mapping_with_uid(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a", "Alpha", tag_uid="04:ab:cd:12:34:56:78")
    m = mapper.get_mapping(id_)
    assert m is not None
    assert m[1] == "04:ab:cd:12:34:56:78"


def test_get_mapping_returns_6_tuple(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a", "Alpha", shuffle=True, tag_uid="aa:bb")
    m = mapper.get_mapping(id_)
    assert m == (id_, "aa:bb", "uri_a", "Alpha", True, False)


def test_get_mapping_nonexistent_id(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    assert mapper.get_mapping(999) is None


def test_update_mapping_by_id(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a", "Alpha")
    mapper.update_mapping(id_, "uri_b", "Beta", tag_uid="aa:bb")
    m = mapper.get_mapping(id_)
    assert m is not None
    assert m[1] == "aa:bb"
    assert m[2] == "uri_b"
    assert m[3] == "Beta"


def test_update_mapping_duplicate_uid_raises(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.create_mapping("uri_a", tag_uid="uid1")
    id2 = mapper.create_mapping("uri_b")
    with pytest.raises(sqlite3.IntegrityError):
        mapper.update_mapping(id2, "uri_b", tag_uid="uid1")


def test_update_mapping_clear_uid(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    id_ = mapper.create_mapping("uri_a", tag_uid="aa:bb")
    mapper.update_mapping(id_, "uri_a", tag_uid=None)
    m = mapper.get_mapping(id_)
    assert m is not None
    assert m[1] is None


def test_migration_from_old_schema(temp_db: str) -> None:
    # Simulate a pre-migration database with the old tag_uid-as-PK schema
    conn = sqlite3.connect(temp_db)
    conn.execute(
        """
        CREATE TABLE tags (
            tag_uid TEXT PRIMARY KEY,
            media_uri TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            shuffle INTEGER NOT NULL DEFAULT 0,
            image_data TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("INSERT INTO tags VALUES ('uid1', 'uri_a', 'Alpha', 0, '')")
    conn.execute("INSERT INTO tags VALUES ('uid2', 'uri_b', 'Beta', 1, 'imgdata')")
    conn.commit()
    conn.close()

    # Migration runs automatically when TagMapper is instantiated
    mapper = TagMapper(db_path=temp_db)

    mappings = mapper.get_all_mappings()
    assert len(mappings) == 2
    uids = {m[1] for m in mappings}
    assert uids == {"uid1", "uid2"}
    # Each row now has an integer id
    assert all(isinstance(m[0], int) for m in mappings)
    # Data integrity preserved
    uid1_row = next(m for m in mappings if m[1] == "uid1")
    assert uid1_row[2] == "uri_a"
    assert uid1_row[3] == "Alpha"
    assert uid1_row[4] is False
    # Image data survived
    uid2_id = next(m[0] for m in mappings if m[1] == "uid2")
    rows = mapper.get_mappings_with_images([uid2_id])
    assert len(rows) == 1
    assert rows[0][1] == "imgdata"


def test_create_mapping_duplicate_uid_raises(temp_db: str) -> None:
    mapper = TagMapper(db_path=temp_db)
    mapper.create_mapping("uri_a", tag_uid="uid1")
    with pytest.raises(sqlite3.IntegrityError):
        mapper.create_mapping("uri_b", tag_uid="uid1")
