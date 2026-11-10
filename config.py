import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent
DATABASE_PATH = ROOT_DIR / os.getenv("DATABASE_PATH", "database/clippulse.db")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "ClipPulse/0.1 (podcast discovery prototype)"
)

DEFAULT_SEARCHES = [
    "Indian English podcast",
    "technology podcast",
    "business interview podcast",
    "science podcast",
]
