import os
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# Sonos Configuration
SONOS_SPEAKER_NAME: str = os.environ.get("SONOS_SPEAKER_NAME", "Wohnzimmer")

# Database path (default: tags.db in current directory, override for Docker volume mount)
DATABASE_PATH: str = os.environ.get("TONTRAEGER_DB_PATH", "tags.db")
