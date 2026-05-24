"""Shared scraper utilities: user-agents, delays, safe DOM helpers, price parser."""
import asyncio
import random
import re

from playwright.async_api import Page
from  config.settings import get_settings

_s = get_settings()

USER_AGENTS: list[str] = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
]


def random_ua() -> str:
    return random.choice(USER_AGENTS)


async def random_delay() -> None:
    """Randomised pause between requests — basic anti-bot measure."""
    ms = random.randint(_s.scraper_min_delay_ms, _s.scraper_max_delay_ms)
    await asyncio.sleep(ms / 1000.0)


async def safe_text(page: Page, selector: str, default: str = "") -> str:
    """Return inner text of first matching element, or default on any error."""
    try:
        el = await page.query_selector(selector)
        return (await el.inner_text()).strip() if el else default
    except Exception:
        return default


async def safe_attr(page: Page, selector: str, attr: str, default: str = "") -> str:
    """Return attribute value of first matching element, or default."""
    try:
        el = await page.query_selector(selector)
        if el:
            val = await el.get_attribute(attr)
            return (val or default).strip()
        return default
    except Exception:
        return default


def parse_price(text: str) -> float:
    """
    Extract a numeric price from strings like:
      '₹22,999', '22,999.00', '₹ 1,09,990', 'MRP: ₹45000'
    Returns 0.0 if no valid number found.
    """
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0
