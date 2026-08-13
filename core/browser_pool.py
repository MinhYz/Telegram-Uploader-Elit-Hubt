import asyncio
from typing import Dict
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext
from config.settings import HEADLESS, MAX_BROWSER_CONTEXTS
from utils.logger import logger

class BrowserPool:
    """
    High-Efficiency Single-Browser Chromium Pool managing isolated user BrowserContexts.
    Targeted to keep total RAM usage under 300MB on 1GB RAM instances.
    """

    def __init__(self):
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: Dict[str, BrowserContext] = {}
        self._lock = asyncio.Lock()

    async def start(self):
        async with self._lock:
            if not self._playwright:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--disable-gpu",
                        "--single-process",
                        "--no-zygote",
                    ],
                )
                logger.info("BrowserPool initialized with single Chromium instance.")

    async def get_context(self, user_id: str, storage_state_path: str = None) -> BrowserContext:
        await self.start()
        async with self._lock:
            if user_id in self._contexts:
                ctx = self._contexts[user_id]
                try:
                    if ctx.pages:
                        return ctx
                except Exception:
                    pass

            # Enforce max context memory limit
            if len(self._contexts) >= MAX_BROWSER_CONTEXTS:
                oldest_uid = next(iter(self._contexts))
                await self.close_context(oldest_uid)

            kwargs = {
                "viewport": {"width": 1280, "height": 800},
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            if storage_state_path and asyncio.iscoroutinefunction(getattr(storage_state_path, "__init__", None)) is False:
                import os
                if os.path.exists(storage_state_path):
                    kwargs["storage_state"] = storage_state_path

            context = await self._browser.new_context(**kwargs)
            self._contexts[user_id] = context
            logger.debug(f"Created isolated BrowserContext for user: {user_id}")
            return context

    async def close_context(self, user_id: str):
        async with self._lock:
            if user_id in self._contexts:
                ctx = self._contexts.pop(user_id)
                try:
                    await ctx.close()
                    logger.debug(f"Closed BrowserContext for user: {user_id}")
                except Exception as e:
                    logger.warning(f"Error closing context for {user_id}: {e}")

    async def shutdown(self):
        async with self._lock:
            for uid in list(self._contexts.keys()):
                await self.close_context(uid)
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            logger.info("BrowserPool completely shut down.")

browser_pool = BrowserPool()
