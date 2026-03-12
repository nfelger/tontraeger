import json
import os
import pytest
from tontraeger_client.cache import MappingCache


@pytest.fixture
def cache_path(tmp_path):
    return str(tmp_path / "mappings.json")


def test_empty_cache_returns_none(cache_path):
    cache = MappingCache(cache_path)
    assert cache.get_uri("nonexistent") is None


def test_empty_cache_has_no_mappings(cache_path):
    cache = MappingCache(cache_path)
    assert cache.all_mappings() == {}


def test_update_and_get_uri(cache_path):
    cache = MappingCache(cache_path)
    cache.update(
        [
            {"tag_uid": "aaa", "media_uri": "http://example.com/track1", "name": "Track 1"},
            {"tag_uid": "bbb", "media_uri": "STOP", "name": "Stop Card"},
        ]
    )
    assert cache.get_uri("aaa") == "http://example.com/track1"
    assert cache.get_uri("bbb") == "STOP"
    assert cache.get_uri("ccc") is None


def test_update_persists_to_disk(cache_path):
    cache = MappingCache(cache_path)
    cache.update(
        [
            {"tag_uid": "aaa", "media_uri": "http://example.com/track1", "name": "Track 1"},
        ]
    )
    assert os.path.exists(cache_path)
    with open(cache_path) as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["tag_uid"] == "aaa"
    assert data[0]["media_uri"] == "http://example.com/track1"
    assert data[0]["name"] == "Track 1"


def test_load_from_existing_file(cache_path):
    data = [
        {"tag_uid": "x1", "media_uri": "uri1", "name": "First"},
        {"tag_uid": "x2", "media_uri": "uri2", "name": "Second"},
    ]
    with open(cache_path, "w") as f:
        json.dump(data, f)

    cache = MappingCache(cache_path)
    assert cache.get_uri("x1") == "uri1"
    assert cache.get_uri("x2") == "uri2"
    assert len(cache.all_mappings()) == 2


def test_load_from_file_without_name_field(cache_path):
    data = [{"tag_uid": "x1", "media_uri": "uri1"}]
    with open(cache_path, "w") as f:
        json.dump(data, f)

    cache = MappingCache(cache_path)
    assert cache.get_uri("x1") == "uri1"
    assert cache.all_mappings()["x1"] == ("uri1", "")


def test_update_replaces_all_mappings(cache_path):
    cache = MappingCache(cache_path)
    cache.update(
        [
            {"tag_uid": "aaa", "media_uri": "uri1", "name": ""},
        ]
    )
    assert cache.get_uri("aaa") == "uri1"

    cache.update(
        [
            {"tag_uid": "bbb", "media_uri": "uri2", "name": ""},
        ]
    )
    assert cache.get_uri("aaa") is None
    assert cache.get_uri("bbb") == "uri2"


def test_all_mappings_returns_copy(cache_path):
    cache = MappingCache(cache_path)
    cache.update(
        [
            {"tag_uid": "aaa", "media_uri": "uri1", "name": "First"},
        ]
    )
    mappings = cache.all_mappings()
    mappings["extra"] = ("fake", "fake")
    assert "extra" not in cache.all_mappings()


def test_atomic_write_produces_valid_file(cache_path):
    """After update, the file on disk is valid JSON that a new cache can load."""
    cache = MappingCache(cache_path)
    cache.update(
        [
            {"tag_uid": "t1", "media_uri": "u1", "name": "N1"},
            {"tag_uid": "t2", "media_uri": "u2", "name": "N2"},
        ]
    )
    cache2 = MappingCache(cache_path)
    assert cache2.get_uri("t1") == "u1"
    assert cache2.get_uri("t2") == "u2"


def test_file_not_found_on_first_boot(tmp_path):
    """Cache initializes cleanly when the file doesn't exist."""
    cache = MappingCache(str(tmp_path / "does_not_exist.json"))
    assert cache.get_uri("any") is None
    assert cache.all_mappings() == {}


def test_corrupt_json_file_starts_empty(cache_path):
    """A corrupted cache file doesn't crash — the cache starts empty."""
    with open(cache_path, "w") as f:
        f.write("{truncated garbage")

    cache = MappingCache(cache_path)
    assert cache.get_uri("any") is None
    assert cache.all_mappings() == {}


def test_wrong_shape_json_file_starts_empty(cache_path):
    """A cache file with unexpected JSON shape (e.g. a dict) doesn't crash."""
    with open(cache_path, "w") as f:
        json.dump({"not": "a list"}, f)

    cache = MappingCache(cache_path)
    assert cache.get_uri("any") is None
    assert cache.all_mappings() == {}


def test_update_with_empty_list_clears_cache(cache_path):
    cache = MappingCache(cache_path)
    cache.update([{"tag_uid": "aaa", "media_uri": "uri1", "name": ""}])
    assert cache.get_uri("aaa") == "uri1"

    cache.update([])
    assert cache.get_uri("aaa") is None
    assert cache.all_mappings() == {}
