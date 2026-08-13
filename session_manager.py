import json
from datetime import datetime
from pathlib import Path
from playwright.async_api import Browser, BrowserContext, Page
from config import SESSION_FILE, DOWNLOAD_DIR, OWNER_ID, logger


class AdminStore:
    """Manages Owner & Admin Telegram IDs for administrative privilege enforcement."""

    def __init__(self, file_path: Path = DOWNLOAD_DIR / "admins.json"):
        self.file_path = file_path
        self.owner_id = str(OWNER_ID)

    def load_admins(self) -> set:
        admins = {self.owner_id}
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    admins.update([str(a) for a in data.get("admins", [])])
            except Exception as e:
                logger.error(f"Error loading admin list: {e}")
        return admins

    def is_admin(self, user_id: str) -> bool:
        return str(user_id) in self.load_admins()

    def is_owner(self, user_id: str) -> bool:
        return str(user_id) == self.owner_id

    def add_admin(self, user_id: str) -> bool:
        admins = self.load_admins()
        admins.add(str(user_id))
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump({"admins": list(admins)}, f, ensure_ascii=False, indent=2)
            logger.info(f"Added user {user_id} to admin list")
            return True
        except Exception as e:
            logger.error(f"Failed to add admin {user_id}: {e}")
            return False

    def remove_admin(self, user_id: str) -> bool:
        if str(user_id) == self.owner_id:
            return False  # Owner cannot be removed
        admins = self.load_admins()
        if str(user_id) in admins:
            admins.remove(str(user_id))
            try:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump({"admins": list(admins)}, f, ensure_ascii=False, indent=2)
                logger.info(f"Removed user {user_id} from admin list")
                return True
            except Exception as e:
                logger.error(f"Failed to remove admin {user_id}: {e}")
        return False


class UserStore:
    """Manages user credentials per Telegram user for multi-account login and background auto-relogin."""

    def __init__(self, file_path: Path = DOWNLOAD_DIR / "user_credentials.json"):
        self.file_path = file_path

    def load_users(self) -> dict:
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading user credentials: {e}")
        return {}

    def save_user(self, user_id: str, msv: str, password: str, chat_id: int = None, username: str = None, token: str = None):
        users = self.load_users()
        users[str(user_id)] = {
            "user_id": str(user_id),
            "chat_id": chat_id,
            "username": username or "",
            "msv": msv,
            "password": password,
            "token": token or users.get(str(user_id), {}).get("token", ""),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(users, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved credentials for user {user_id} (MSV: {msv})")
        except Exception as e:
            logger.error(f"Failed to save user credentials: {e}")

    def get_user(self, user_id: str) -> dict:
        users = self.load_users()
        return users.get(str(user_id))

    def remove_user(self, user_id: str):
        users = self.load_users()
        if str(user_id) in users:
            del users[str(user_id)]
            try:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump(users, f, ensure_ascii=False, indent=2)
                logger.info(f"Removed credentials for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to update user credentials file: {e}")


class SessionManager:
    """Manages browser session persistence per user and validation via storage_state."""

    def __init__(self, user_id: str = None, session_path: Path = None):
        if session_path:
            self.session_path = Path(session_path)
        elif user_id:
            session_dir = DOWNLOAD_DIR / "sessions"
            session_dir.mkdir(parents=True, exist_ok=True)
            self.session_path = session_dir / f"session_{user_id}.json"
        else:
            self.session_path = SESSION_FILE

    def has_session(self) -> bool:
        """Check if storage state file exists and is not empty."""
        return self.session_path.exists() and self.session_path.stat().st_size > 0

    async def save_session(self, context: BrowserContext) -> str:
        """Save browser storage_state (cookies, localStorage) to file and return MoodleSession token."""
        token = ""
        try:
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(self.session_path))
            cookies = await context.cookies()
            for c in cookies:
                if c.get("name") == "MoodleSession":
                    token = c.get("value", "")
                    break
            logger.info(f"Saved session state to {self.session_path} (Token: {token[:8]}...)")
        except Exception as e:
            logger.error(f"Failed to save session state: {e}")
        return token

    def create_session_from_token(self, token: str) -> bool:
        """Create a Playwright storage_state.json directly from a MoodleSession token."""
        token_clean = token.strip()
        if not token_clean:
            return False

        storage_data = {
            "cookies": [
                {
                    "name": "MoodleSession",
                    "value": token_clean,
                    "domain": "elit.hubt.edu.vn",
                    "path": "/",
                    "expires": -1,
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None"
                }
            ],
            "origins": []
        }

        try:
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.session_path, "w", encoding="utf-8") as f:
                json.dump(storage_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Created session from token for {self.session_path}")
            return True
        except Exception as e:
            logger.error(f"Error creating session from token: {e}")
            return False

    async def create_context(self, browser: Browser) -> BrowserContext:
        """Create a BrowserContext, reusing user session file if present."""
        if self.has_session():
            logger.info(f"Loading existing session from {self.session_path}")
            try:
                context = await browser.new_context(
                    storage_state=str(self.session_path),
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                return context
            except Exception as e:
                logger.warning(f"Error loading session file, creating fresh context: {e}")
        
        logger.info("Creating clean browser context (no session loaded).")
        return await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

    async def is_session_expired(self, page: Page) -> bool:
        """Determine if page was redirected to login page or session expired."""
        current_url = page.url.lower()
        if "login/index.php" in current_url:
            return True
        
        # Additional check for login form inputs
        username_input = await page.query_selector("input[name='username'], #username")
        if username_input:
            is_visible = await username_input.is_visible()
            if is_visible:
                return True
        return False

    def clear_session(self):
        """Delete storage state file."""
        if self.session_path.exists():
            try:
                self.session_path.unlink()
                logger.info(f"Cleared session state file {self.session_path}")
            except Exception as e:
                logger.error(f"Failed to delete session state file: {e}")
