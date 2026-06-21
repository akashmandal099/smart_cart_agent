"""
Agent Node 2 — Product Search

Scrapes product listings from all requested platforms in parallel.
Checks TTL cache before scraping. Filters results by price range.
"""
import asyncio

from  cache import ttl_cache as cache
from  config.settings import get_settings
from  models.agent_state import AgentState
from  models.product import Platform
from  scrapers.amazon import AmazonScraper
from  scrapers.flipkart import FlipkartScraper

_s = get_settings()
_scrapers = {
    Platform.AMAZON:   AmazonScraper(),
    Platform.FLIPKART: FlipkartScraper(),
}


async def product_search_node(state: AgentState) -> AgentState:
    intent = state["intent"]

    tasks = [
        _fetch_platform(p, intent.product, intent.price_min, intent.price_max)
        for p in intent.platforms
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    products = []
    for r in results:
        if isinstance(r, list):
            products.extend(r)

    # Secondary price filter — scraper URL params are best-effort
    if intent.price_max < 99_999_999:
        products = [p for p in products if p.base_price <= intent.price_max]
    if intent.price_min > 0:
        products = [p for p in products if p.base_price >= intent.price_min]

    # Brand filter if hint provided
    if intent.brand_hint:
        brand = intent.brand_hint.lower()
        products = [
            p for p in products
            if brand in p.title.lower() or (p.brand and brand in p.brand.lower())
        ]
    print(f"2. Found {len(products)} products after filtering")
    return {**state, "raw_products": products}


async def _fetch_platform(
    platform: Platform,
    query: str,
    price_min: float,
    price_max: float,
) -> list:
    cached = cache.get_products(query, platform.value, price_min, price_max)
    if cached is not None:
        return cached
    scraper = _scrapers[platform]
    products = await scraper.search_products(
        query, price_min, price_max, _s.scraper_max_per_platform
    )
    cache.set_products(query, platform.value, price_min, price_max, products)
    return products
