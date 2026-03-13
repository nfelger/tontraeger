from tontraeger_client.config import NFC_DAEMON_PATH


def test_nfc_daemon_path_default():
    """NFC_DAEMON_PATH defaults to /usr/local/bin/nfc-daemon."""
    assert NFC_DAEMON_PATH == "/usr/local/bin/nfc-daemon"
