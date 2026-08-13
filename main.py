import asyncio
import uvicorn
from fastapi import FastAPI
from config.settings import DEFAULT_CHAT_ID
from database.db import db
from core.browser_pool import browser_pool
from services.scheduler import adaptive_scheduler
from services.failover import failover_service
from bot.telegram_bot import bot_app
from utils.system_monitor import get_system_stats
from utils.cleaner import storage_cleaner
from utils.logger import logger

# FastAPI App for REST & Health Checks
api_app = FastAPI(
    title="HUBT Moodle Automation Framework (AIO)",
    version="2.0.0",
    description="Production-grade, enterprise-ready, overengineered Moodle LMS Automation System",
)

@api_app.get("/healthz")
async def health_check():
    """Health check endpoint for Docker / High Availability Failover."""
    return {"status": "ok", "service": "HUBT Moodle Framework", "active_master": failover_service.is_active_master}

@api_app.get("/metrics")
async def metrics():
    """Prometheus-style JSON system metrics endpoint."""
    return get_system_stats()

async def background_moodle_check():
    """Background scheduled job checking assignments & attendance across registered users."""
    logger.info("Executing scheduled background Moodle check job...")
    try:
        users = await db.get_all_active_users()
        if not users:
            logger.debug("No active users registered for background check.")
            return

        for u in users:
            uid = u["user_id"]
            from services.moodle_scraper import MoodleScraperService
            scraper = MoodleScraperService(uid)
            try:
                assignments = await scraper.check_today_classes_and_assignments()
                for a in assignments:
                    aid = a["assignment_id"]
                    if not await db.is_assignment_seen(aid):
                        await db.mark_assignment_seen(aid, a)
                        logger.info(f"Background check discovered new unsubmitted assignment #{aid} for user {uid}")
            except Exception as ex_usr:
                logger.warning(f"Error checking user {uid}: {ex_usr}")
    except Exception as e:
        logger.error(f"Error in background_moodle_check: {e}")

async def start_framework():
    logger.info("==========================================================")
    logger.info("Starting HUBT Moodle Automation Framework (AIO) v2.0...")
    logger.info("==========================================================")

    # 1. Initialize SQLite Database & Tables
    await db.init_db()

    # 2. Initialize Low-RAM Playwright Browser Pool
    await browser_pool.start()

    # 3. Start High-Availability Heartbeat
    asyncio.create_task(failover_service.start_heartbeat())

    # 4. Start Adaptive Polling Scheduler
    adaptive_scheduler.start(background_moodle_check)

    # 5. Build and Start Telegram Bot
    telegram_application = bot_app.build()
    if telegram_application:
        async with telegram_application:
            await telegram_application.start()
            await telegram_application.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram Bot App initialized and polling successfully!")

            # 6. Run FastAPI Server
            config = uvicorn.Config(app=api_app, host="0.0.0.0", port=8000, log_level="warning")
            server = uvicorn.Server(config)
            await server.serve()

            await telegram_application.updater.stop()
            await telegram_application.stop()

if __name__ == "__main__":
    try:
        asyncio.run(start_framework())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Framework shutting down cleanly...")
