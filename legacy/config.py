import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# Workspace Root Directory
BASE_DIR = Path(__file__).resolve().parent

# Telegram & API Credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_CHAT_ID = os.getenv("DEFAULT_CHAT_ID", "")
OWNER_ID = str(os.getenv("OWNER_ID", "5158297014"))

# Scheduler Config
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "30"))

# LMS Target URLs
BASE_URL = "https://elit.hubt.edu.vn"
LOGIN_URL = f"{BASE_URL}/login/index.php"
PORTAL_URL = f"{BASE_URL}/local/portal/index.php"
ASSIGNMENT_VIEW_URL = f"{BASE_URL}/mod/assign/view.php?id={{id}}"
ASSIGNMENT_EDIT_URL = f"{BASE_URL}/mod/assign/view.php?id={{id}}&action=editsubmission"

# File & Storage Paths
SESSION_FILE = BASE_DIR / "session.json"
STATE_DB_FILE = BASE_DIR / "submitted_jobs.json"
DOWNLOAD_DIR = BASE_DIR / "downloads"
SCREENSHOT_DIR = BASE_DIR / "screenshots"
LOG_FILE = BASE_DIR / "bot.log"

# Headless browser setting
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")

# Ensure required directories exist
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# Configure Logging
def setup_logging():
    logger = logging.getLogger("ELitBot")
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s - %(name)s: %(message)s"
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # Rotating File handler (5 MB max per file, keep 3 backups)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger

logger = setup_logging()
