import os
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# Sonos Configuration
SONOS_SPEAKER_NAME: str = os.environ.get("SONOS_SPEAKER_NAME", "Wohnzimmer")

# Server Configuration
TONTRAEGER_SERVER: str = os.environ.get("TONTRAEGER_SERVER", "http://tontraeger.local:5000")

# Cache Configuration
CACHE_PATH: str = os.environ.get("TONTRAEGER_CACHE_PATH", "mappings.json")
