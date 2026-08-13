import asyncio
import aiohttp
from config.settings import FAILOVER_PRIMARY_URL, FAILOVER_STANDBY_URL, IS_STANDBY_NODE
from utils.logger import logger

class HighAvailabilityFailoverService:
    """Heartbeat ping mechanism between primary VPS and secondary standby node."""

    def __init__(self):
        self.is_active_master = not IS_STANDBY_NODE
        self.primary_url = FAILOVER_PRIMARY_URL
        self.standby_url = FAILOVER_STANDBY_URL
        self.failed_pings = 0

    async def start_heartbeat(self):
        if not IS_STANDBY_NODE:
            logger.info("Node running in PRIMARY Master Mode.")
            return

        logger.info("Node running in STANDBY Secondary Mode. Monitoring primary heartbeat...")
        while True:
            await asyncio.sleep(60)
            if not self.primary_url:
                continue

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.primary_url}/healthz", timeout=10) as resp:
                        if resp.status == 200:
                            self.failed_pings = 0
                            logger.debug("Heartbeat ping to Primary VPS successful.")
                        else:
                            self.failed_pings += 1
            except Exception as e:
                self.failed_pings += 1
                logger.warning(f"Heartbeat ping to Primary VPS failed ({self.failed_pings}/3): {e}")

            if self.failed_pings >= 3 and not self.is_active_master:
                self.is_active_master = True
                logger.critical("PRIMARY VPS FAILED 3 HEARTBEATS! PROMOTING STANDBY NODE TO ACTIVE MASTER!")

failover_service = HighAvailabilityFailoverService()
