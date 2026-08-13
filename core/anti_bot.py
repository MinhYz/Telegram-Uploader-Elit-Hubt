import random
import asyncio
from playwright.async_api import Page
from utils.logger import logger

class AntiBotStealth:
    """Anti-Bot Evasion Engine providing humanized interactions and stealth script injections."""

    @staticmethod
    async def apply_stealth(page: Page):
        """Mask navigator.webdriver and inject stealth scripts into page."""
        stealth_js = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
            window.chrome = { runtime: {} };
        """
        await page.add_init_script(stealth_js)
        logger.debug("Applied AntiBotStealth scripts to Playwright Page.")

    @staticmethod
    async def human_type(page: Page, selector: str, text: str, min_delay_ms: int = 50, max_delay_ms: int = 150):
        """Type text into field with randomized human keystroke delays (50-150ms)."""
        element = await page.query_selector(selector)
        if not element:
            raise ValueError(f"Target element not found for human typing: {selector}")
        
        await element.click()
        await element.fill("")
        for char in text:
            await element.type(char)
            delay = random.randint(min_delay_ms, max_delay_ms) / 1000.0
            await asyncio.sleep(delay)

    @staticmethod
    async def human_move_and_click(page: Page, selector: str):
        """Move cursor naturally and click element."""
        element = await page.query_selector(selector)
        if element:
            box = await element.bounding_box()
            if box:
                # Randomize click position inside element bounds
                x = box["x"] + box["width"] * random.uniform(0.2, 0.8)
                y = box["y"] + box["height"] * random.uniform(0.2, 0.8)
                await page.mouse.move(x, y, steps=random.randint(5, 15))
                await asyncio.sleep(random.uniform(0.05, 0.2))
                await page.mouse.click(x, y)
                return
        await page.click(selector)
