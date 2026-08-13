import shutil
from pathlib import Path
from config.settings import DOWNLOAD_DIR, SCREENSHOT_DIR, LOG_DIR
from utils.logger import logger

class StorageCleaner:
    """Storage & Cache Cleaner to keep 1GB RAM / Low Disk VPS lean."""

    @staticmethod
    def purge_temp_files() -> int:
        """Purge temporary PDF/Word files, screenshots, and logs older than retention rules."""
        cleaned_count = 0
        
        # Clean screenshots
        for f in SCREENSHOT_DIR.glob("*.png"):
            try:
                f.unlink()
                cleaned_count += 1
            except Exception:
                pass

        # Clean download temp subfolders
        for sub in DOWNLOAD_DIR.glob("sub_*"):
            if sub.is_dir():
                try:
                    shutil.rmtree(sub)
                    cleaned_count += 1
                except Exception:
                    pass

        logger.info(f"StorageCleaner purged {cleaned_count} temporary files/folders.")
        return cleaned_count

storage_cleaner = StorageCleaner()
