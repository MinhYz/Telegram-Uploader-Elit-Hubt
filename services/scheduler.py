import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config.settings import CHECK_INTERVAL_PEAK_MIN, CHECK_INTERVAL_OFFPEAK_MIN, CHECK_INTERVAL_FAST_MIN
from utils.logger import logger

class AdaptiveSchedulerService:
    """
    APScheduler with Adaptive Polling Rate:
    - Peak Hours (07:00 - 22:00): Polls every 15 minutes.
    - Off-peak Hours (22:00 - 07:00): Polls every 2 hours.
    - Near-Deadline (Within 2 hours of submission deadline): Fast-polling every 1 minute.
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.current_interval_min = CHECK_INTERVAL_PEAK_MIN

    def determine_optimal_interval(self, upcoming_deadlines: list = None) -> int:
        now = datetime.datetime.now()
        
        # Check if near deadline (within 2 hours of deadline)
        if upcoming_deadlines:
            for dl in upcoming_deadlines:
                if isinstance(dl, datetime.datetime):
                    diff_minutes = (dl - now).total_seconds() / 60
                    if 0 < diff_minutes <= 120:
                        logger.info(f"AdaptiveScheduler: Upcoming deadline detected in {diff_minutes:.0f}m! Switched to Fast-Polling (1m).")
                        return CHECK_INTERVAL_FAST_MIN

        # Check peak vs off-peak hours
        if 7 <= now.hour < 22:
            return CHECK_INTERVAL_PEAK_MIN
        else:
            return CHECK_INTERVAL_OFFPEAK_MIN

    def start(self, job_func, *args, **kwargs):
        interval = self.determine_optimal_interval()
        self.scheduler.add_job(
            job_func,
            "interval",
            minutes=interval,
            id="moodle_auto_check",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info(f"AdaptiveScheduler started with polling interval: {interval} minutes.")

    def update_polling_rate(self, new_interval_min: int, job_func):
        self.scheduler.reschedule_job(
            "moodle_auto_check",
            trigger="interval",
            minutes=new_interval_min,
        )
        logger.info(f"AdaptiveScheduler rescheduled polling job to {new_interval_min} minutes.")

adaptive_scheduler = AdaptiveSchedulerService()
