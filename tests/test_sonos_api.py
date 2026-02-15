import pytest
from unittest.mock import patch, MagicMock
from tontraeger.sonos_api import SonosAPI


@pytest.fixture
def mock_soco_speaker():
    """Create a mock SoCo speaker object."""
    speaker = MagicMock()
    speaker.player_name = "Living Room"
    speaker.clear_queue = MagicMock()
    speaker.add_uri_to_queue = MagicMock()
    speaker.play_from_queue = MagicMock()
    speaker.pause = MagicMock()
    return speaker


@pytest.fixture
def sonos_api(mock_soco_speaker):
    """Create a SonosAPI instance with mocked discovery."""
    with patch('tontraeger.sonos_api.soco.discover') as mock_discover:
        mock_discover.return_value = [mock_soco_speaker]
        api = SonosAPI('Living Room')
        yield api


def test_init_speaker_found(mock_soco_speaker):
    """Test successful speaker discovery."""
    with patch('tontraeger.sonos_api.soco.discover') as mock_discover:
        mock_discover.return_value = [mock_soco_speaker]
        api = SonosAPI('Living Room')
        assert api._speaker == mock_soco_speaker
        assert api.speaker_name == 'Living Room'


def test_init_no_speakers_found():
    """Test exception when no speakers found on network."""
    with patch('tontraeger.sonos_api.soco.discover') as mock_discover:
        mock_discover.return_value = None
        with pytest.raises(Exception, match="No Sonos speakers found on network"):
            SonosAPI('Living Room')


def test_init_speaker_name_not_found():
    """Test exception when specified speaker name doesn't match any discovered speakers."""
    mock_speaker1 = MagicMock()
    mock_speaker1.player_name = "Bedroom"
    mock_speaker2 = MagicMock()
    mock_speaker2.player_name = "Kitchen"

    with patch('tontraeger.sonos_api.soco.discover') as mock_discover:
        mock_discover.return_value = [mock_speaker1, mock_speaker2]
        with pytest.raises(Exception, match="Speaker 'Living Room' not found"):
            SonosAPI('Living Room')


def test_play_uri_native(sonos_api, mock_soco_speaker):
    """Test playing a native Sonos URI uses add_uri_to_queue."""
    uri = "x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0"

    sonos_api.play_uri(uri)

    mock_soco_speaker.clear_queue.assert_called_once()
    mock_soco_speaker.add_uri_to_queue.assert_called_once_with(uri)
    mock_soco_speaker.play_from_queue.assert_called_once_with(0)


def test_play_uri_share_link(sonos_api, mock_soco_speaker):
    """Test playing a share link URL uses ShareLinkPlugin."""
    url = "https://open.example.com/album/abc123"

    with patch('tontraeger.sonos_api.ShareLinkPlugin') as mock_plugin_class:
        mock_plugin = MagicMock()
        mock_plugin_class.return_value = mock_plugin

        sonos_api.play_uri(url)

        mock_soco_speaker.clear_queue.assert_called_once()
        mock_plugin_class.assert_called_once_with(mock_soco_speaker)
        mock_plugin.add_share_link_to_queue.assert_called_once_with(url)
        mock_soco_speaker.add_uri_to_queue.assert_not_called()
        mock_soco_speaker.play_from_queue.assert_called_once_with(0)


def test_stop_playback(sonos_api, mock_soco_speaker):
    """Test stopping playback."""
    sonos_api.stop_playback()
    mock_soco_speaker.pause.assert_called_once()


def test_play_uri_no_speaker():
    """Test that play_uri raises exception when speaker not initialized."""
    api = SonosAPI.__new__(SonosAPI)
    api.speaker_name = "Test"
    api._speaker = None

    with pytest.raises(Exception, match="Speaker not initialized"):
        api.play_uri("x-sonosapi-radio:test")


def test_get_current_track_uri(sonos_api, mock_soco_speaker):
    """Test getting the URI of the currently playing track."""
    mock_soco_speaker.get_current_track_info.return_value = {
        "uri": "x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0",
        "title": "Some Station",
    }
    assert sonos_api.get_current_track_uri() == "x-sonosapi-radio:s25111?sid=254&flags=8224&sn=0"


def test_get_current_track_uri_nothing_playing(sonos_api, mock_soco_speaker):
    """Test that None is returned when nothing is playing."""
    mock_soco_speaker.get_current_track_info.return_value = {"uri": ""}
    assert sonos_api.get_current_track_uri() is None


def test_get_current_track_uri_no_speaker():
    """Test that get_current_track_uri raises exception when speaker not initialized."""
    api = SonosAPI.__new__(SonosAPI)
    api.speaker_name = "Test"
    api._speaker = None

    with pytest.raises(Exception, match="Speaker not initialized"):
        api.get_current_track_uri()


def test_stop_playback_no_speaker():
    """Test that stop_playback raises exception when speaker not initialized."""
    api = SonosAPI.__new__(SonosAPI)
    api.speaker_name = "Test"
    api._speaker = None

    with pytest.raises(Exception, match="Speaker not initialized"):
        api.stop_playback()
