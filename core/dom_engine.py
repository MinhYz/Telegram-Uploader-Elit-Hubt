import time
import asyncio
from typing import List, Optional
from playwright.async_api import Page, ElementHandle
from utils.logger import logger

class CircuitBreakerOpenException(Exception):
    """Raised when Circuit Breaker is active due to continuous Moodle errors."""
    pass

class CircuitBreaker:
    """Circuit Breaker Pattern: Pauses Moodle operations for 30 minutes if 5xx errors persist."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout_sec: int = 1800):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.failure_count = 0
        self.last_failure_time = 0

    def is_open(self) -> bool:
        if self.failure_count >= self.failure_threshold:
            time_since_failure = time.time() - self.last_failure_time
            if time_since_failure < self.recovery_timeout_sec:
                return True
            else:
                # Half-open state reset
                self.failure_count = 0
                logger.info("CircuitBreaker reset to normal operation state.")
        return False

    def record_failure(self, status_code: int = 500):
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(f"CircuitBreaker recorded Moodle failure #{self.failure_count} (Status: {status_code})")
        if self.failure_count >= self.failure_threshold:
            logger.error(f"CircuitBreaker OPENED! Moodle operations paused for {self.recovery_timeout_sec // 60} minutes.")

    def record_success(self):
        self.failure_count = 0

circuit_breaker = CircuitBreaker()

class DOMEngine:
    """Fuzzy matching CSS/XPath selector engine with resilient fallbacks."""

    @staticmethod
    async def find_element(page: Page, selectors: List[str], timeout_ms: int = 5000) -> Optional[ElementHandle]:
        """Attempt to find element by iterating through fuzzy selector candidates."""
        for selector in selectors:
            try:
                elem = await page.wait_for_selector(selector, timeout=timeout_ms, state="visible")
                if elem:
                    return elem
            except Exception:
                continue
        return None

    @staticmethod
    async def click_fuzzy(page: Page, selectors: List[str], timeout_ms: int = 5000) -> bool:
        """Find element using fuzzy selectors and click it."""
        elem = await DOMEngine.find_element(page, selectors, timeout_ms)
        if elem:
            await elem.click()
            return True
        return False

    @staticmethod
    def check_response_status(status_code: int):
        """Validate response status code for Circuit Breaker handling."""
        if status_code in (500, 502, 503, 504):
            circuit_breaker.record_failure(status_code)
            if circuit_breaker.is_open():
                raise CircuitBreakerOpenException(f"Moodle returned server error {status_code}. Circuit Breaker active.")
        else:
            circuit_breaker.record_success()
