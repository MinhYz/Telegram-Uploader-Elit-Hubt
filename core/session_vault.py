import json
from pathlib import Path
from typing import Dict, Any, Optional
from config.settings import SESSION_DIR
from database.crypto import encrypt_data, decrypt_data
from utils.logger import logger

class SessionVault:
    """Manages encrypted user session cookies and local storage tokens."""

    def __init__(self, session_dir: Path = SESSION_DIR):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def get_session_file(self, user_id: str) -> Path:
        return self.session_dir / f"session_{user_id}.enc"

    def has_session(self, user_id: str) -> bool:
        return self.get_session_file(user_id).exists()

    def save_session_state(self, user_id: str, state_dict: Dict[str, Any]):
        """Encrypt and save browser storage state JSON."""
        file_path = self.get_session_file(user_id)
        try:
            raw_json = json.dumps(state_dict)
            encrypted = encrypt_data(raw_json)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(encrypted)
            logger.debug(f"Saved encrypted session state for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to save session state for user {user_id}: {e}")

    def load_session_state(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load and decrypt browser storage state JSON."""
        file_path = self.get_session_file(user_id)
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                encrypted = f.read()
            raw_json = decrypt_data(encrypted)
            return json.loads(raw_json)
        except Exception as e:
            logger.error(f"Failed to load/decrypt session state for user {user_id}: {e}")
            return None

    def delete_session(self, user_id: str):
        file_path = self.get_session_file(user_id)
        if file_path.exists():
            file_path.unlink()
            logger.info(f"Deleted session file for user {user_id}")

session_vault = SessionVault()
