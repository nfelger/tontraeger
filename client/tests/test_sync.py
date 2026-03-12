import asyncio
from unittest.mock import MagicMock, patch

import pytest
import requests

from tontraeger_client.cache import MappingCache
from tontraeger_client.sync import MappingSync


@pytest.fixture
def cache(tmp_path):
    return MappingCache(str(tmp_path / "mappings.json"))


@pytest.fixture
def sync(cache):
    return MappingSync("http://server.local:5000", cache)


def _mock_response(status_code=200, json_data=None, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    return resp


class TestPoll:
    @patch("tontraeger_client.sync.requests.get")
    def test_200_updates_cache(self, mock_get, sync, cache):
        mappings = [
            {"tag_uid": "aaa", "media_uri": "uri1", "name": "Track 1"},
            {"tag_uid": "bbb", "media_uri": "STOP", "name": "Stop"},
        ]
        mock_get.return_value = _mock_response(
            200,
            json_data={"mappings": mappings},
            headers={"ETag": "abc123"},
        )

        result = sync.poll()

        assert result is True
        assert cache.get_uri("aaa") == "uri1"
        assert cache.get_uri("bbb") == "STOP"

    @patch("tontraeger_client.sync.requests.get")
    def test_304_skips_update(self, mock_get, sync, cache):
        # First poll: get data
        mappings = [{"tag_uid": "aaa", "media_uri": "uri1", "name": ""}]
        mock_get.return_value = _mock_response(
            200,
            json_data={"mappings": mappings},
            headers={"ETag": "etag1"},
        )
        sync.poll()
        assert cache.get_uri("aaa") == "uri1"

        # Second poll: 304 Not Modified
        mock_get.return_value = _mock_response(304)
        result = sync.poll()

        assert result is False
        # Cache should still have previous data
        assert cache.get_uri("aaa") == "uri1"

    @patch("tontraeger_client.sync.requests.get")
    def test_connection_error_does_not_crash(self, mock_get, sync, cache):
        mock_get.side_effect = requests.ConnectionError("server down")

        result = sync.poll()

        assert result is False
        assert cache.all_mappings() == {}

    @patch("tontraeger_client.sync.requests.get")
    def test_etag_sent_on_subsequent_polls(self, mock_get, sync):
        # First poll: receive ETag
        mock_get.return_value = _mock_response(
            200,
            json_data={"mappings": []},
            headers={"ETag": "etag-value"},
        )
        sync.poll()

        # Second poll: verify ETag is sent
        mock_get.return_value = _mock_response(304)
        sync.poll()

        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["If-None-Match"] == "etag-value"

    @patch("tontraeger_client.sync.requests.get")
    def test_no_etag_on_first_poll(self, mock_get, sync):
        mock_get.return_value = _mock_response(
            200,
            json_data={"mappings": []},
            headers={"ETag": "e1"},
        )
        sync.poll()

        first_call_kwargs = mock_get.call_args_list[0][1]
        assert "If-None-Match" not in first_call_kwargs["headers"]

    @patch("tontraeger_client.sync.requests.get")
    def test_unexpected_status_returns_false(self, mock_get, sync):
        mock_get.return_value = _mock_response(500)

        result = sync.poll()
        assert result is False

    @patch("tontraeger_client.sync.requests.get")
    def test_timeout_error_does_not_crash(self, mock_get, sync):
        mock_get.side_effect = requests.Timeout("timed out")

        result = sync.poll()
        assert result is False

    @patch("tontraeger_client.sync.requests.get")
    def test_malformed_json_does_not_crash(self, mock_get, sync, cache):
        """Server returns 200 with invalid JSON body — sync loop continues."""
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {}
        resp.json.side_effect = ValueError("No JSON object could be decoded")
        mock_get.return_value = resp

        result = sync.poll()

        assert result is False
        assert cache.all_mappings() == {}


class TestReportUnknownTag:
    @pytest.mark.asyncio
    @patch("tontraeger_client.sync.requests.post")
    async def test_posts_tag_uid(self, mock_post, sync):
        mock_post.return_value = _mock_response(200)

        await sync.report_unknown_tag("tag123")

        mock_post.assert_called_once_with(
            "http://server.local:5000/api/unknown-tags",
            json={"tag_uid": "tag123"},
            timeout=5,
        )

    @pytest.mark.asyncio
    @patch("tontraeger_client.sync.requests.post")
    async def test_connection_error_does_not_crash(self, mock_post, sync):
        mock_post.side_effect = requests.ConnectionError("server down")

        # Should not raise
        await sync.report_unknown_tag("tag123")


class TestRun:
    @pytest.mark.asyncio
    async def test_run_calls_poll_periodically(self, sync, monkeypatch):
        """run() calls poll and sleeps in a loop."""
        poll_count = 0
        sleep_intervals: list[float] = []

        def counting_poll() -> bool:
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 3:
                raise _StopLoop()
            return False

        sync.poll = counting_poll  # type: ignore[assignment]

        async def tracking_sleep(s: float) -> None:
            sleep_intervals.append(s)

        import tontraeger_client.sync as sync_module

        monkeypatch.setattr(sync_module.asyncio, "sleep", tracking_sleep)

        with pytest.raises(_StopLoop):
            await sync.run(interval=7.0)

        assert poll_count == 3
        assert sleep_intervals == [7.0, 7.0]  # sleeps between polls (3rd poll raises before sleep)


class _StopLoop(Exception):
    """Sentinel exception to break out of the infinite run() loop in tests."""
