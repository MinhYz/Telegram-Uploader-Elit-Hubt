import datetime
from typing import List, Dict, Any
from config.settings import QUIET_HOURS_START, QUIET_HOURS_END
from utils.logger import logger

class QuietHoursManager:
    """Suppresses notifications between 23:00 - 06:00, batching them into a 07:00 morning digest."""

    def __init__(self):
        self.pending_notifications: List[Dict[str, Any]] = []

    def is_quiet_hours(self) -> bool:
        now_hour = datetime.datetime.now().hour
        if QUIET_HOURS_START > QUIET_HOURS_END:
            return now_hour >= QUIET_HOURS_START or now_hour < QUIET_HOURS_END
        return QUIET_HOURS_START <= now_hour < QUIET_HOURS_END

    def queue_notification(self, notification: Dict[str, Any]):
        self.pending_notifications.append(notification)
        logger.info(f"Queued notification for morning digest (Total pending: {len(self.pending_notifications)})")

    def pop_morning_digest(self) -> List[Dict[str, Any]]:
        digest = list(self.pending_notifications)
        self.pending_notifications.clear()
        return digest

quiet_hours_mgr = QuietHoursManager()
