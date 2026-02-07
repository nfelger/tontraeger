import pytest
from unittest.mock import patch, MagicMock
from spotibox.sonos_api import SonosAPI


@pytest.fixture
def mock_soco_speaker():
    """Create a mock SoCo speaker object."""
    speaker = MagicMock()
    speaker.player_name = "Living Room"
    speaker.clear_queue = MagicMock()
    speaker.play_from_queue = MagicMock()
    speaker.pause = MagicMock()
    return speaker


@pytest.fixture
def sonos_api(mock_soco_speaker):
    """Create a SonosAPI instance with mocked discovery."""
    with patch('spotibox.sonos_api.soco.discover') as mock_discover:
        mock_discover.return_value = [mock_soco_speaker]
        api = SonosAPI('Living Room')
        yield api


def test_init_speaker_found(mock_soco_speaker):
    """Test successful speaker discovery."""
    with patch('spotibox.sonos_api.soco.discover') as mock_discover:
        mock_discover.return_value = [mock_soco_speaker]
        api = SonosAPI('Living Room')
        assert api._speaker == mock_soco_speaker
        assert api.speaker_name == 'Living Room'


def test_init_no_speakers_found():
    """Test exception when no speakers found on network."""
    with patch('spotibox.sonos_api.soco.discover') as mock_discover:
        mock_discover.return_value = None
        with pytest.raises(Exception, match="No Sonos speakers found on network"):
            SonosAPI('Living Room')


def test_init_speaker_name_not_found():
    """Test exception when specified speaker name doesn't match any discovered speakers."""
    mock_speaker1 = MagicMock()
    mock_speaker1.player_name = "Bedroom"
    mock_speaker2 = MagicMock()
    mock_speaker2.player_name = "Kitchen"

    with patch('spotibox.sonos_api.soco.discover') as mock_discover:
        mock_discover.return_value = [mock_speaker1, mock_speaker2]
        with pytest.raises(Exception, match="Speaker 'Living Room' not found"):
            SonosAPI('Living Room')


def test_start_playlist(sonos_api, mock_soco_speaker):
    """Test starting playlist with share URL."""
    share_url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

    with patch('spotibox.sonos_api.ShareLinkPlugin') as mock_plugin_class:
        mock_plugin = MagicMock()
        mock_plugin_class.return_value = mock_plugin

        sonos_api.start_playlist(share_url)

        # Verify the correct sequence of operations
        mock_soco_speaker.clear_queue.assert_called_once()
        mock_plugin_class.assert_called_once_with(mock_soco_speaker)
        mock_plugin.add_share_link_to_queue.assert_called_once_with(share_url)
        mock_soco_speaker.play_from_queue.assert_called_once_with(0)


def test_stop_playback(sonos_api, mock_soco_speaker):
    """Test stopping playback."""
    sonos_api.stop_playback()
    mock_soco_speaker.pause.assert_called_once()


def test_start_playlist_no_speaker():
    """Test that start_playlist raises exception when speaker not initialized."""
    api = SonosAPI.__new__(SonosAPI)
    api.speaker_name = "Test"
    api._speaker = None

    with pytest.raises(Exception, match="Speaker not initialized"):
        api.start_playlist("https://open.spotify.com/playlist/test")


def test_stop_playback_no_speaker():
    """Test that stop_playback raises exception when speaker not initialized."""
    api = SonosAPI.__new__(SonosAPI)
    api.speaker_name = "Test"
    api._speaker = None

    with pytest.raises(Exception, match="Speaker not initialized"):
        api.stop_playback()
