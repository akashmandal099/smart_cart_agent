"""
Agent Node 3 — Offer Fetcher

Scrapes raw offer text + T&C from each product's detail page.
Runs concurrently with a semaphore to respect rate limits.
Checks TTL cache before scraping.
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


async def offer_fetcher_node(state: AgentState) -> AgentState:
    products = state["raw_products"]
    sem = asyncio.Semaphore(_s.scraper_max_concurrent)

    async def fetch_one(product):
        async with sem:
            cached = cache.get_offers(product.product_id, product.platform.value)
            if cached is not None:
                return product.product_id, cached
            scraper = _scrapers[product.platform]
            offers = await scraper.scrape_offers(product)
            cache.set_offers(product.product_id, product.platform.value, offers)
            return product.product_id, offers

    results = await asyncio.gather(*[fetch_one(p) for p in products], return_exceptions=True)

    raw_offers: dict = {}
    for r in results:
        if isinstance(r, tuple):
            pid, offers = r
            raw_offers[pid] = offers
    print(f"3. Fetched offers for {len(raw_offers)} products: {raw_offers}")
    return {**state, "raw_offers": raw_offers}
