"""
Amazon India scraper.

All CSS selectors are isolated in the SEL dict at the top.
When Amazon updates its page layout, only update SEL — core logic stays unchanged.
"""
from __future__ import annotations

import asyncio
import uuid

from playwright.async_api import async_playwright

from  config.settings import get_settings
from  models.offer import Offer, OfferType
from  models.product import Platform, Product
from .base import BaseScraper
from .utils import parse_price, random_delay, random_ua, safe_attr, safe_text

_s = get_settings()

# ── Selectors — update here only when Amazon changes layout ───────────────────
SEL = {
    # Search page
    "product_card":  '[data-component-type="s-search-result"]',
    "title":         "h2 a span",
    "price_whole":   ".a-price-whole",
    "mrp":           ".a-text-price .a-offscreen",
    "rating":        ".a-icon-alt",
    "reviews":       '[aria-label*="ratings"] span, .a-size-base.s-underline-text',
    "product_link":  "h2 a",
    "image":         ".s-image",

    # Product detail page
    "offer_section": "#sopp_feature_div li, #mir-layout-DELIVERY_BLOCK li, .a-list-item",
    "offer_terms":   ".a-expander-content p, .a-expander-content",
}


class AmazonScraper(BaseScraper):

    async def search_products(
        self,
        query: str,
        price_min: float,
        price_max: float,
        max_results: int,
    ) -> list[Product]:
        url = (
            f"https://www.amazon.in/s?k={query.replace(' ', '+')}"
            f"&rh=p_36%3A{int(price_min * 100)}-{int(price_max * 100)}"
            f"&sort=review-rank"
        )
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=_s.scraper_headless)
            page = await browser.new_page(user_agent=random_ua())
            try:
                await page.goto(
                    url,
                    timeout=_s.scraper_timeout_ms,
                    wait_until="domcontentloaded",
                )
                await random_delay()
                products = await self._parse_search_page(page, max_results)
            finally:
                await browser.close()
        print(f"Amazon: Scraped {len(products)} products for query '{query}'")
        return products

    async def scrape_offers(self, product: Product) -> list[Offer]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=_s.scraper_headless)
            page = await browser.new_page(user_agent=random_ua())
            try:
                await page.goto(
                    product.product_url,
                    timeout=_s.scraper_timeout_ms,
                    wait_until="domcontentloaded",
                )
                await random_delay()
                offers = await self._parse_offer_sections(page, product)
            except Exception:
                offers = []
            finally:
                await browser.close()
        print(f"Amazon: Scraped {len(offers)} offers for product '{product.title}'")
        return offers

    # ── private ───────────────────────────────────────────────────────────────

    async def _parse_search_page(self, page, max_results: int) -> list[Product]:
        cards = await page.query_selector_all(SEL["product_card"])
        sem = asyncio.Semaphore(_s.scraper_max_concurrent)

        async def extract(card) -> Product | None:
            async with sem:
                try:
                    title = await safe_text(card, SEL["title"])
                    if not title:
                        return None

                    price_text = await safe_text(card, SEL["price_whole"])
                    price = parse_price(price_text)
                    if price == 0:
                        return None

                    mrp_text = await safe_text(card, SEL["mrp"])
                    mrp = parse_price(mrp_text) or None

                    rating_text = await safe_text(card, SEL["rating"])
                    rating = None
                    if rating_text:
                        try:
                            rating = float(rating_text.split()[0])
                        except ValueError:
                            pass

                    reviews_text = await safe_text(card, SEL["reviews"])
                    review_count = None
                    if reviews_text:
                        digits = "".join(c for c in reviews_text if c.isdigit())
                        review_count = int(digits) if digits else None

                    href = await safe_attr(card, SEL["product_link"], "href")
                    product_url = (
                        f"https://www.amazon.in{href}"
                        if href.startswith("/")
                        else href
                    )
                    image_url = await safe_attr(card, SEL["image"], "src")

                    asin = (
                        product_url.split("/dp/")[1].split("/")[0]
                        if "/dp/" in product_url
                        else str(uuid.uuid4())
                    )

                    return Product(
                        platform=Platform.AMAZON,
                        product_id=asin,
                        title=title,
                        base_price=price,
                        mrp=mrp,
                        rating=rating,
                        review_count=review_count,
                        image_url=image_url,
                        product_url=product_url,
                    )
                except Exception:
                    return None

        results = await asyncio.gather(*[extract(c) for c in cards[:max_results]])
        return [p for p in results if p is not None]

    async def _parse_offer_sections(self, page, product: Product) -> list[Offer]:
        """
        Scrapes raw offer text + T&C.
        Structured parsing (bank, discount %, cap) is done by the LLM tc_parser node.
        The scraper stays dumb — it just collects text.
        """
        offers: list[Offer] = []
        items = await page.query_selector_all(SEL["offer_section"])

        for i, item in enumerate(items[:15]):   # cap at 15 offer rows
            text = ""
            try:
                text = (await item.inner_text()).strip()
            except Exception:
                continue
            if not text or len(text) < 5:
                continue

            # Try to expand and capture full T&C text
            terms = ""
            try:
                expander = await item.query_selector(SEL["offer_terms"])
                if expander:
                    terms = (await expander.inner_text()).strip()
            except Exception:
                pass

            offers.append(
                Offer(
                    offer_id=f"amz_{product.product_id}_{i}",
                    product_id=product.product_id,
                    platform="amazon",
                    # offer_type is a placeholder — LLM tc_parser will correct it
                    offer_type=OfferType.BANK_DISCOUNT,
                    title=text,
                    terms=terms,
                )
            )
        return offers
