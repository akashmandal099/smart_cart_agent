"""
Flipkart India scraper.

All CSS selectors isolated in SEL — update here only when Flipkart changes layout.
"""
from __future__ import annotations

import asyncio
import re
import uuid

from playwright.async_api import async_playwright

from  config.settings import get_settings
from  models.offer import Offer, OfferType
from  models.product import Platform, Product
from .base import BaseScraper
from .utils import parse_price, random_delay, random_ua, safe_attr, safe_text

_s = get_settings()

# ── Selectors — update here only when Flipkart changes layout ─────────────────
SEL = {
    # Search page
    "product_card":  "div[data-id]",
    "title":         "div.KzDlHZ, a.WKTcLC, div._4rR01T",
    "price":         "div.Nx9bqj, div._30jeq3",
    "mrp":           "div.yRaY8j, div._3I9_wc",
    "rating":        "div.XQDdHH, span._1lRcqv",
    "reviews":       "span.Wphh3N, span._13vcmD",
    "product_link":  "a.CGtC98, a.s1Q9rs, a._1fQZEK",
    "image":         "img.DByuf4, img._396cs4",

    # Product detail page
    "offer_row":     "div._6csep4 li, li.d8M7sf, div._3xFhiH li",
    "offer_terms":   "div._3LWZlK, div._1wyTYP",
    "login_dismiss": "button._2KpZ6l._2doB4z, button.close-button",
}


class FlipkartScraper(BaseScraper):

    async def search_products(
        self,
        query: str,
        price_min: float,
        price_max: float,
        max_results: int,
    ) -> list[Product]:
        q = query.replace(" ", "%20")
        url = (
            f"https://www.flipkart.com/search?q={q}"
            f"&p%5B%5D=facets.price_range.from%3D{int(price_min)}"
            f"&p%5B%5D=facets.price_range.to%3D{int(price_max)}"
            f"&sort=POPULARITY"
        )
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=_s.scraper_headless)
            context = await browser.new_context(user_agent=random_ua())
            page = await context.new_page()
            try:
                await page.goto(
                    url,
                    timeout=_s.scraper_timeout_ms,
                    wait_until="domcontentloaded",
                )
                await random_delay()
                await self._dismiss_login(page)
                products = await self._parse_search_page(page, max_results)
            finally:
                await browser.close()
        print(f"Flipkart: Scraped {len(products)} products for query '{query}'")
        return products

    async def scrape_offers(self, product: Product) -> list[Offer]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=_s.scraper_headless)
            context = await browser.new_context(user_agent=random_ua())
            page = await context.new_page()
            try:
                await page.goto(
                    product.product_url,
                    timeout=_s.scraper_timeout_ms,
                    wait_until="domcontentloaded",
                )
                await random_delay()
                await self._dismiss_login(page)
                offers = await self._parse_offer_sections(page, product)
            except Exception:
                offers = []
            finally:
                await browser.close()
        print(f"Flipkart: Scraped {len(offers)} offers for product '{product.title}'")
        return offers

    # ── private ───────────────────────────────────────────────────────────────

    async def _dismiss_login(self, page) -> None:
        """Dismiss Flipkart login popup if it appears."""
        try:
            await page.click(SEL["login_dismiss"], timeout=2500)
        except Exception:
            pass

    async def _parse_search_page(self, page, max_results: int) -> list[Product]:
        cards = await page.query_selector_all(SEL["product_card"])
        products: list[Product] = []

        for card in cards[:max_results]:
            try:
                title = await safe_text(card, SEL["title"])
                if not title:
                    continue

                price_text = await safe_text(card, SEL["price"])
                price = parse_price(price_text)
                if price == 0:
                    continue

                mrp_text = await safe_text(card, SEL["mrp"])
                mrp = parse_price(mrp_text) or None

                rating_text = await safe_text(card, SEL["rating"])
                rating = None
                if rating_text:
                    try:
                        rating = float(rating_text.strip())
                    except ValueError:
                        pass

                reviews_text = await safe_text(card, SEL["reviews"])
                review_count = None
                if reviews_text:
                    m = re.search(r"[\d,]+", reviews_text)
                    if m:
                        review_count = int(m.group().replace(",", ""))

                href = await safe_attr(card, SEL["product_link"], "href")
                product_url = (
                    f"https://www.flipkart.com{href}"
                    if href.startswith("/")
                    else href
                )
                image_url = await safe_attr(card, SEL["image"], "src")

                pid_match = re.search(r"pid=([A-Z0-9]+)", product_url)
                product_id = pid_match.group(1) if pid_match else str(uuid.uuid4())

                products.append(
                    Product(
                        platform=Platform.FLIPKART,
                        product_id=product_id,
                        title=title,
                        base_price=price,
                        mrp=mrp,
                        rating=rating,
                        review_count=review_count,
                        image_url=image_url,
                        product_url=product_url,
                    )
                )
            except Exception:
                continue

        return products

    async def _parse_offer_sections(self, page, product: Product) -> list[Offer]:
        """
        Scrapes raw offer text + T&C from Flipkart product page.
        Structured parsing done by tc_parser (LLM) — scraper stays dumb.
        """
        offers: list[Offer] = []
        items = await page.query_selector_all(SEL["offer_row"])

        for i, item in enumerate(items[:15]):
            text = ""
            try:
                text = (await item.inner_text()).strip()
            except Exception:
                continue
            if not text or len(text) < 5:
                continue

            terms = ""
            try:
                t_el = await item.query_selector(SEL["offer_terms"])
                if t_el:
                    terms = (await t_el.inner_text()).strip()
            except Exception:
                pass

            offers.append(
                Offer(
                    offer_id=f"fk_{product.product_id}_{i}",
                    product_id=product.product_id,
                    platform="flipkart",
                    offer_type=OfferType.BANK_DISCOUNT,   # LLM will correct
                    title=text,
                    terms=terms,
                )
            )
        return offers
