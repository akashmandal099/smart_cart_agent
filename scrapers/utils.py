"""
Shared scraper utilities — parse_price, random_delay, random_ua,
safe_text / safe_attr helpers for Playwright element handles.
"""
from __future__ import annotations

import asyncio
import random
import re
from typing import Optional

from playwright.async_api import ElementHandle

from config.settings import get_settings

_s = get_settings()

# ── User-agent pool ───────────────────────────────────────────────────────────
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]


def random_ua() -> str:
    return random.choice(_USER_AGENTS)


async def random_delay() -> None:
    """Human-like delay between scraper actions."""
    ms = random.randint(_s.scraper_min_delay_ms, _s.scraper_max_delay_ms)
    await asyncio.sleep(ms / 1000)


# ── Price parser ─────────────────────────────────────────────────────────────

def parse_price(text: Optional[str]) -> float:
    """Extract a numeric price from a string like '₹20,999' or '20999'."""
    if not text:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ── Playwright helpers ────────────────────────────────────────────────────────

async def safe_text(handle: ElementHandle, selector: str) -> str:
    """Query selector inside handle and return inner text, or '' on failure."""
    try:
        el = await handle.query_selector(selector)
        if el:
            return (await el.inner_text()).strip()
    except Exception:
        pass
    return ""


async def safe_attr(handle: ElementHandle, selector: str, attr: str) -> str:
    """Query selector inside handle and return attribute value, or '' on failure."""
    try:
        el = await handle.query_selector(selector)
        if el:
            val = await el.get_attribute(attr)
            return (val or "").strip()
    except Exception:
        pass
    return ""