
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent

DATABASE_PATH = ROOT_DIR / os.getenv(
    "DATABASE_PATH", "database/clippulse.db"
)

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

USER_AGENT = os.getenv(
    "USER_AGENT",
    "ClipPulse/0.2 (podcast intelligence prototype)"
)

DEFAULT_SEARCHES = [
    "Indian English podcast",
    "technology podcast",
    "business interview podcast",
    "science podcast",
]

# Audio processing
AUDIO_DIR = ROOT_DIR / "data" / "audio"
TRANSCRIPT_DIR = ROOT_DIR / "data" / "transcripts"

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv(
    "WHISPER_COMPUTE_TYPE", "int8"
)

MAX_AUDIO_SIZE_MB = int(
    os.getenv("MAX_AUDIO_SIZE_MB", "1000")
)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
# Video processing
VIDEO_DIR = ROOT_DIR / "data" / "videos"
OUTPUT_DIR = ROOT_DIR / "output" / "clips"

VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30