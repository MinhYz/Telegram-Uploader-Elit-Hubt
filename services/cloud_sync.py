import aiohttp
from typing import Dict, Any
from config.settings import NOTION_TOKEN, NOTION_DATABASE_ID, GOOGLE_CALENDAR_ID
from utils.logger import logger

class CloudSyncService:
    """Multi-Cloud Deadline Synchronization (Notion Workspace & Google Calendar)."""

    @staticmethod
    async def sync_to_notion(assignment: Dict[str, Any]) -> bool:
        """Create Notion database task entry for assignment."""
        if not NOTION_TOKEN or not NOTION_DATABASE_ID:
            logger.debug("Notion token/database ID not configured. Skipping Notion sync.")
            return False

        url = "https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        payload = {
            "parent": {"database_id": NOTION_DATABASE_ID},
            "properties": {
                "Title": {"title": [{"text": {"content": assignment.get("title", "Bài tập HUBT")}}]},
                "Course": {"rich_text": [{"text": {"content": assignment.get("course_name", "")}}]},
                "URL": {"url": assignment.get("url", "")},
                "Status": {"select": {"name": "Chưa nộp" if not assignment.get("is_submitted") else "Đã nộp"}},
            },
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status in (200, 201):
                        logger.info(f"Synced assignment #{assignment.get('assignment_id')} to Notion!")
                        return True
                    else:
                        text = await resp.text()
                        logger.warning(f"Notion sync failed ({resp.status}): {text}")
                        return False
        except Exception as e:
            logger.error(f"Error syncing to Notion: {e}")
            return False

cloud_sync = CloudSyncService()
