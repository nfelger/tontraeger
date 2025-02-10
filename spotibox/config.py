# spotibox/config.py
import os
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

CLIENT_ID: str = os.environ.get("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET: str = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI: str = os.environ.get("SPOTIFY_REDIRECT_URI", "")
SCOPE: str = 'user-read-playback-state user-modify-playback-state'
