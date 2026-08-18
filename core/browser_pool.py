import os
import json
import asyncio
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Error as PlaywrightError
from config.settings import HEADLESS, MAX_BROWSER_CONTEXTS
from utils.logger import logger

class BrowserPool:
    """
    High-Efficiency Self-Healing Single-Browser Chromium Pool managing isolated user BrowserContexts.
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

            if not self._browser or not self._browser.is_connected():
                if self._browser:
                    try:
                        await self._browser.close()
                    except Exception:
                        pass
                self._contexts.clear()
                self._browser = await self._playwright.chromium.launch(
                    headless=HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--disable-gpu",
                        "--no-zygote",
                    ],
                )
                logger.info("BrowserPool initialized with single Chromium instance.")

    async def get_context(self, user_id: str, storage_state: Optional[Dict[str, Any] | str] = None) -> BrowserContext:
        await self.start()
        async with self._lock:
            # Check existing context validity
            if user_id in self._contexts:
                ctx = self._contexts[user_id]
                try:
                    # Test if context is still active and valid
                    _ = ctx.pages
                    return ctx
                except Exception:
                    logger.warning(f"Existing context for {user_id} was closed or invalid. Recreating...")
                    self._contexts.pop(user_id, None)

            # Enforce max context memory limit
            if len(self._contexts) >= MAX_BROWSER_CONTEXTS:
                oldest_uid = next(iter(self._contexts))
                await self._close_context_unlocked(oldest_uid)

            kwargs: Dict[str, Any] = {
                "viewport": {"width": 1280, "height": 800},
                "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            if storage_state:
                if isinstance(storage_state, dict) and (storage_state.get("cookies") or storage_state.get("origins")):
                    kwargs["storage_state"] = storage_state
                elif isinstance(storage_state, (str, os.PathLike)) and os.path.exists(storage_state):
                    try:
                        with open(storage_state, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, dict):
                                kwargs["storage_state"] = data
                    except Exception as ex_json:
                        logger.warning(f"Storage state file {storage_state} is not valid JSON ({ex_json}), ignoring.")

            try:
                context = await self._browser.new_context(**kwargs)
            except Exception as e:
                logger.warning(f"Failed to create new_context ({e}). Restarting browser pool...")
                # Browser might have crashed, force restart browser
                if self._browser:
                    try:
                        await self._browser.close()
                    except Exception:
                        pass
                self._contexts.clear()
                self._browser = await self._playwright.chromium.launch(
                    headless=HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--disable-gpu",
                        "--no-zygote",
                    ],
                )
                context = await self._browser.new_context(**kwargs)

            self._contexts[user_id] = context
            logger.debug(f"Created isolated BrowserContext for user: {user_id}")
            return context

    async def _close_context_unlocked(self, user_id: str):
        if user_id in self._contexts:
            ctx = self._contexts.pop(user_id)
            try:
                await ctx.close()
                logger.debug(f"Closed BrowserContext for user: {user_id}")
            except Exception as e:
                logger.warning(f"Error closing context for {user_id}: {e}")

    async def close_context(self, user_id: str):
        async with self._lock:
            await self._close_context_unlocked(user_id)

    async def shutdown(self):
        async with self._lock:
            for uid in list(self._contexts.keys()):
                await self._close_context_unlocked(uid)
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            logger.info("BrowserPool completely shut down.")

browser_pool = BrowserPool()
