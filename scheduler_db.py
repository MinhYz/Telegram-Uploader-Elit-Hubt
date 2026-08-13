import json
from datetime import datetime
from pathlib import Path
from config import STATE_DB_FILE, logger


class StateTracker:
    """Handles persistence of seen assignments and bot runtime states."""

    def __init__(self, db_file: Path = STATE_DB_FILE):
        self.db_file = db_file
        self.data = self._load()

    def _load(self) -> dict:
        if self.db_file.exists():
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading state DB {self.db_file}: {e}")
        return {
            "seen_assignments": {},
            "auto_check_enabled": True,
            "last_check_timestamp": None,
        }

    def _save(self):
        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving state DB {self.db_file}: {e}")

    def is_assignment_seen(self, assignment_id: str) -> bool:
        return str(assignment_id) in self.data.get("seen_assignments", {})

    def mark_assignment_seen(self, assignment_id: str, details: dict = None):
        if "seen_assignments" not in self.data:
            self.data["seen_assignments"] = {}
        
        self.data["seen_assignments"][str(assignment_id)] = {
            "title": details.get("title", "") if details else "",
            "course": details.get("course_name", "") if details else "",
            "first_seen": datetime.now().isoformat(),
        }
        self._save()

    def is_auto_check_enabled(self) -> bool:
        return self.data.get("auto_check_enabled", True)

    def set_auto_check_enabled(self, enabled: bool):
        self.data["auto_check_enabled"] = enabled
        self._save()

    def update_last_check(self):
        self.data["last_check_timestamp"] = datetime.now().isoformat()
        self._save()

    def get_last_check(self) -> str:
        return self.data.get("last_check_timestamp")

    def get_seen_count(self) -> int:
        return len(self.data.get("seen_assignments", {}))
