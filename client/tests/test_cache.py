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
    cache.update([
        {"tag_uid": "aaa", "media_uri": "http://example.com/track1", "name": "Track 1", "shuffle": False},
        {"tag_uid": "bbb", "media_uri": "STOP", "name": "Stop Card", "shuffle": False},
    ])
    assert cache.get_uri("aaa") == "http://example.com/track1"
    assert cache.get_uri("bbb") == "STOP"
    assert cache.get_uri("ccc") is None


def test_update_persists_to_disk(cache_path):
    cache = MappingCache(cache_path)
    cache.update([
        {"tag_uid": "aaa", "media_uri": "http://example.com/track1", "name": "Track 1", "shuffle": False},
    ])
    assert os.path.exists(cache_path)
    with open(cache_path) as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["tag_uid"] == "aaa"
    assert data[0]["media_uri"] == "http://example.com/track1"
    assert data[0]["name"] == "Track 1"
    assert data[0]["shuffle"] is False


def test_update_persists_shuffle_true_to_disk(cache_path):
    cache = MappingCache(cache_path)
    cache.update([
        {"tag_uid": "s1", "media_uri": "spotify:playlist:xyz", "name": "Radio", "shuffle": True},
    ])
    with open(cache_path) as f:
        data = json.load(f)
    assert data[0]["shuffle"] is True


def test_load_from_existing_file(cache_path):
    data = [
        {"tag_uid": "x1", "media_uri": "uri1", "name": "First", "shuffle": False},
        {"tag_uid": "x2", "media_uri": "uri2", "name": "Second", "shuffle": True},
    ]
    with open(cache_path, "w") as f:
        json.dump(data, f)

    cache = MappingCache(cache_path)
    assert cache.get_uri("x1") == "uri1"
    assert cache.get_uri("x2") == "uri2"
    assert len(cache.all_mappings()) == 2


def test_update_replaces_all_mappings(cache_path):
    cache = MappingCache(cache_path)
    cache.update([
        {"tag_uid": "aaa", "media_uri": "uri1", "name": "", "shuffle": False},
    ])
    assert cache.get_uri("aaa") == "uri1"

    cache.update([
        {"tag_uid": "bbb", "media_uri": "uri2", "name": "", "shuffle": False},
    ])
    assert cache.get_uri("aaa") is None
    assert cache.get_uri("bbb") == "uri2"


def test_all_mappings_returns_copy(cache_path):
    cache = MappingCache(cache_path)
    cache.update([
        {"tag_uid": "aaa", "media_uri": "uri1", "name": "First", "shuffle": False},
    ])
    mappings = cache.all_mappings()
    mappings["extra"] = ("fake", "fake", False)
    assert "extra" not in cache.all_mappings()


def test_atomic_write_produces_valid_file(cache_path):
    """After update, the file on disk is valid JSON that a new cache can load."""
    cache = MappingCache(cache_path)
    cache.update([
        {"tag_uid": "t1", "media_uri": "u1", "name": "N1", "shuffle": False},
        {"tag_uid": "t2", "media_uri": "u2", "name": "N2", "shuffle": True},
    ])
    cache2 = MappingCache(cache_path)
    assert cache2.get_uri("t1") == "u1"
    assert cache2.get_uri("t2") == "u2"


def test_get_shuffle_true(cache_path):
    cache = MappingCache(cache_path)
    cache.update([
        {"tag_uid": "s1", "media_uri": "spotify:playlist:xyz", "name": "Radio", "shuffle": True},
    ])
    assert cache.get_shuffle("s1") is True


def test_get_shuffle_false(cache_path):
    cache = MappingCache(cache_path)
    cache.update([
        {"tag_uid": "s1", "media_uri": "spotify:playlist:xyz", "name": "Ordered", "shuffle": False},
    ])
    assert cache.get_shuffle("s1") is False


def test_get_shuffle_unknown_tag(cache_path):
    cache = MappingCache(cache_path)
    assert cache.get_shuffle("unknown") is False


def test_file_not_found_on_first_boot(tmp_path):
    """Cache initializes cleanly when the file doesn't exist."""
    cache = MappingCache(str(tmp_path / "does_not_exist.json"))
    assert cache.get_uri("any") is None
    assert cache.all_mappings() == {}


def test_corrupt_json_file_starts_empty(cache_path):
    """A corrupt cache file is logged and treated as empty, not a crash."""
    with open(cache_path, "w") as f:
        f.write("not valid json{{{")

    cache = MappingCache(cache_path)
    assert cache.all_mappings() == {}


def test_wrong_shape_json_file_starts_empty(cache_path):
    """A cache file containing a JSON dict (not a list) is treated as empty."""
    with open(cache_path, "w") as f:
        json.dump({"not": "a list"}, f)

    cache = MappingCache(cache_path)
    assert cache.all_mappings() == {}
