import random
import asyncio
from playwright.async_api import Page
from utils.logger import logger

class AntiBotStealth:
    """Anti-Bot Evasion Engine providing humanized interactions and stealth script injections."""

    @staticmethod
    async def apply_stealth(page: Page, block_media: bool = True):
        """Mask navigator.webdriver and inject stealth scripts into page."""
        stealth_js = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
            window.chrome = { runtime: {} };
        """
        await page.add_init_script(stealth_js)
        if block_media:
            try:
                await page.route(
                    "**/*",
                    lambda route: route.abort() if route.request.resource_type in ("image", "media", "font") and "pluginfile" not in route.request.url else route.continue_()
                )
            except Exception:
                pass
        logger.debug("Applied AntiBotStealth scripts to Playwright Page.")

    @staticmethod
    async def human_type(page: Page, selector: str, text: str, min_delay_ms: int = 30, max_delay_ms: int = 80):
        """Type text into field with randomized human keystroke delays (30-80ms) using Playwright Locator."""
        locator = page.locator(selector).first
        await locator.wait_for(state="visible", timeout=15000)
        await locator.click()
        await locator.fill("")
        for char in text:
            await locator.type(char, delay=random.randint(min_delay_ms, max_delay_ms))

    @staticmethod
    async def human_move_and_click(page: Page, selector: str):
        """Move cursor naturally and click element using Playwright Locator."""
        locator = page.locator(selector).first
        await locator.wait_for(state="visible", timeout=15000)
        try:
            box = await locator.bounding_box()
            if box:
                x = box["x"] + box["width"] * random.uniform(0.2, 0.8)
                y = box["y"] + box["height"] * random.uniform(0.2, 0.8)
                await page.mouse.move(x, y, steps=random.randint(5, 15))
                await page.mouse.click(x, y)
            else:
                await locator.click()
        except Exception:
            await locator.click()
