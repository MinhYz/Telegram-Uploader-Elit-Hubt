import os
from pathlib import Path
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_CHAT_ID = os.getenv("DEFAULT_CHAT_ID", "")
OWNER_ID = str(os.getenv("OWNER_ID", "5158297014"))
WEB_SHELL_PIN = os.getenv("WEB_SHELL_PIN", "123456")

# AES Key for Data Encryption
AES_SECRET_KEY = os.getenv("AES_SECRET_KEY", "")
if not AES_SECRET_KEY:
    # Generate a fallback runtime key if not set
    AES_SECRET_KEY = Fernet.generate_key().decode()

# LMS URLs
BASE_URL = os.getenv("BASE_URL", "https://elit.hubt.edu.vn")
LOGIN_URL = f"{BASE_URL}/login/index.php"
PORTAL_URL = f"{BASE_URL}/local/portal/index.php"
ASSIGNMENT_VIEW_URL = f"{BASE_URL}/mod/assign/view.php?id={{id}}"
ASSIGNMENT_EDIT_URL = f"{BASE_URL}/mod/assign/view.php?id={{id}}&action=editsubmission"
ATTENDANCE_VIEW_URL = f"{BASE_URL}/mod/attendance/view.php?id={{id}}"

# Polling Config
CHECK_INTERVAL_PEAK_MIN = int(os.getenv("CHECK_INTERVAL_PEAK_MIN", "15"))
CHECK_INTERVAL_OFFPEAK_MIN = int(os.getenv("CHECK_INTERVAL_OFFPEAK_MIN", "120"))
CHECK_INTERVAL_FAST_MIN = int(os.getenv("CHECK_INTERVAL_FAST_MIN", "1"))

# Headless & Performance
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("true", "1", "yes")
MAX_BROWSER_CONTEXTS = int(os.getenv("MAX_BROWSER_CONTEXTS", "3"))

# Paths
DOWNLOAD_DIR = BASE_DIR / "downloads"
SCREENSHOT_DIR = BASE_DIR / "screenshots"
SESSION_DIR = DOWNLOAD_DIR / "sessions"
LOG_DIR = BASE_DIR / "logs"
DB_PATH = BASE_DIR / "data" / "hubt_framework.db"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
SESSION_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Quiet Hours (23:00 - 06:00)
QUIET_HOURS_START = 23
QUIET_HOURS_END = 6

# Integrations
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "")
FAILOVER_PRIMARY_URL = os.getenv("FAILOVER_PRIMARY_URL", "")
FAILOVER_STANDBY_URL = os.getenv("FAILOVER_STANDBY_URL", "")
IS_STANDBY_NODE = os.getenv("IS_STANDBY_NODE", "false").lower() in ("true", "1", "yes")
