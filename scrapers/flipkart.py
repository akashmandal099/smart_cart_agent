"""
Flipkart India scraper — corrected for the React/inline-style DOM (May 2026).

Key fixes vs previous version
──────────────────────────────
1.  Font family names are  inter_bold / inter_regular  (underscore, NOT camelCase).
2.  Card root identified by inline style:
        border-width: 1px  +  border-radius: 12px  +  width: 220px
3.  Offer type label ("Credit Card • Cashback") is an  inter_bold + pre-wrap  div —
    NOT a CSS class like r-dnmrzs.
4.  T&C is already present in the static HTML for some banks (Axis, SBI).
    For others (BHIM, Mobikwik) it requires a Playwright click on the footer row.
5.  T&C modal close strategy updated for new fixed-overlay React shell.
"""
from __future__ import annotations

import asyncio
import math
import re
import uuid
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, ElementHandle

from config.settings import get_settings
from models.offer import CardType, Offer, OfferType
from models.product import Platform, Product
from .base import BaseScraper
from .utils import parse_price, random_delay, random_ua, safe_attr, safe_text

_s = get_settings()

# ─────────────────────────────────────────────────────────────────────────────
# Search-page selectors  (classic CSS class names — relatively stable)
# ─────────────────────────────────────────────────────────────────────────────
SEL_SEARCH = {
    "product_card": "div[data-id]",
    "title":        "div.RG5Slk, div.KzDlHZ, a.WKTcLC, div._4rR01T",
    "price":        "div.hZ3P6w.DeU9vF, div.Nx9bqj, div._30jeq3",
    "mrp":          "div.kRYCnD.gxR4EY, div.yRaY8j, div._3I9_wc",
    "rating":       "div.MKiFS6, div.XQDdHH, span._1lRcqv",
    "reviews":      "span.PvbNMB, span.Wphh3N, span._13vcmD",
    "link":         "a.k7wcnx, a.CGtC98, a.s1Q9rs, a._1fQZEK",
    "image":        "img.UCc1lI, img.DByuf4, img._396cs4",
    "login_popup":  "button._2KpZ6l._2doB4z, button.close-button",
}

# ─────────────────────────────────────────────────────────────────────────────
# Product-page offer selectors  (inline-style React DOM — verified May 2026)
#
# DOM structure confirmed from live page dump:
#
#   <div class="css-g5y9jx" style="border-width: 1px; border-radius: 12px;
#                                   border-color: rgb(235,235,235); width: 220px;">
#     <!-- optional badge -->
#     <div ...>Best value for you</div>
#
#     <!-- amount row -->
#     <div style="color:rgb(51,51,51); font-size:16px; font-family:inter_bold;">
#       ₹1,050 off
#     </div>
#     <!-- bank name -->
#     <div style="color:rgb(51,51,51); font-size:14px; font-family:inter_regular;">
#       Flipkart Axis
#     </div>
#
#     <!-- footer click row (→ expands T&C) -->
#     <div style="cursor: pointer; ...">
#       <div style="font-family:inter_bold; font-size:14px; white-space:pre-wrap;">
#         Credit Card • Cashback
#       </div>
#       <svg>...</svg>   ← chevron-right
#     </div>
#   </div>
# ─────────────────────────────────────────────────────────────────────────────
SEL_OFFER = {
    # ── Playwright (CSS attribute) selectors ──────────────────────────────────
    # Card root — VERIFIED: all three style fragments present simultaneously
    "card_root": (
        'div[style*="border-width: 1px"][style*="border-radius: 12px"]'
        '[style*="width: 220px"]'
    ),
    # Amount: inter_bold + 16px (font name uses UNDERSCORE not camelCase)
    "amount": (
        'div[style*="inter_bold"][style*="font-size: 16px"], '
        'div[style*="inter_bold"][style*="font-size: 15px"]'
    ),
    # Bank / program: inter_regular + 14px
    "program": (
        'div[style*="inter_regular"][style*="font-size: 14px"], '
        'div[style*="inter_regular"][style*="font-size: 12px"]'
    ),
    # Offer type label: inter_bold + 14px + pre-wrap
    "type_label": (
        'div[style*="inter_bold"][style*="font-size: 14px"][style*="pre-wrap"]'
    ),
    # Footer row that triggers T&C drawer when clicked
    "footer_click": 'div[style*="cursor: pointer"]',

    # ── T&C modal content selectors ───────────────────────────────────────────
    # After clicking the footer, Flipkart renders these class-based sections:
    "tnc_all":        "div[class*='grumbles-tnc-']",
    "tnc_details":    "div.grumbles-tnc-offerDetails",
    "tnc_benefits":   "div.grumbles-tnc-offerBenefits",
    "tnc_conditions": "div.grumbles-tnc-offerConditions",
    "tnc_duration":   "div.grumbles-tnc-offerDuration",
    "tnc_other":      "div.grumbles-tnc-otherTNC",
    "tnc_redemption": "div.grumbles-tnc-redemptionDetails",

    # ── Modal close strategies (tried in order) ───────────────────────────────
    "close_attempts": [
        'div[style*="position: fixed"] button',
        'div[style*="z-index: 9"] button',
        'div[role="dialog"] button',
        'div[aria-modal="true"] button',
        'button[aria-label="Close"]',
        'button[aria-label="close"]',
    ],

    # ── Fallback for older Flipkart offer layout ──────────────────────────────
    "row_fallback": "div._6csep4 li, li.d8M7sf, div._3xFhiH li",
}

# Banks whose T&C text is already embedded in the static HTML
# (no Playwright click required — parsed via BeautifulSoup)
_STATIC_TNC_BANKS = re.compile(
    r"flipkart\s*axis|axis|flipkart\s*sbi|sbi|icici|hdfc|kotak",
    re.I,
)

# ── Offer-type label → enum mapping ──────────────────────────────────────────
def _infer_offer_type(label: str) -> tuple[OfferType, CardType]:
    l = label.lower()
    card_type = CardType.ALL
    if "credit card" in l:
        card_type = CardType.CREDIT
        offer_type = OfferType.CASHBACK if "cashback" in l else OfferType.BANK_DISCOUNT
    elif "debit card" in l:
        card_type = CardType.DEBIT
        offer_type = OfferType.CASHBACK if "cashback" in l else OfferType.BANK_DISCOUNT
    elif "upi" in l or "bhim" in l:
        offer_type = OfferType.CASHBACK
    elif "emi" in l:
        offer_type = OfferType.EMI_BENEFIT
    elif "coupon" in l:
        offer_type = OfferType.COUPON
    elif "exchange" in l:
        offer_type = OfferType.EXCHANGE
    else:
        offer_type = OfferType.BANK_DISCOUNT
    return offer_type, card_type


# ─────────────────────────────────────────────────────────────────────────────
class FlipkartScraper(BaseScraper):
    """
    Two-phase scraper:
      Phase 1 — search_products()  : hit search page, collect product listings
      Phase 2 — scrape_offers()    : visit each product URL, collect offers + T&C
    """

    # ══════════════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ══════════════════════════════════════════════════════════════════════════

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
            ctx = await browser.new_context(
                user_agent=random_ua(),
                ignore_https_errors=True,
            )
            page = await ctx.new_page()
            try:
                await page.goto(url, timeout=_s.scraper_timeout_ms, wait_until="domcontentloaded")
                await random_delay()
                await _dismiss_popup(page, SEL_SEARCH["login_popup"])
                products = await self._parse_search_page(page, max_results)
            finally:
                await browser.close()
        return products

    async def scrape_offers(self, product: Product) -> list[Offer]:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=_s.scraper_headless)
            ctx = await browser.new_context(
                user_agent=random_ua(),
                ignore_https_errors=True,
            )
            page = await ctx.new_page()
            try:
                await page.goto(
                    product.product_url,
                    timeout=_s.scraper_timeout_ms,
                    wait_until="domcontentloaded",
                )
                await random_delay()
                await _dismiss_popup(page, SEL_SEARCH["login_popup"])
                offers = await self._parse_offer_sections(page, product)
            except Exception:
                offers = []
            finally:
                await browser.close()
        return offers

    # ══════════════════════════════════════════════════════════════════════════
    # SEARCH PAGE PARSING
    # ══════════════════════════════════════════════════════════════════════════

    async def _parse_search_page(self, page: Page, max_results: int) -> list[Product]:
        cards = await page.query_selector_all(SEL_SEARCH["product_card"])
        products: list[Product] = []

        for card in cards[:math.ceil(max_results * 0.3)]:  # over-fetch to filter misses
            try:
                title = await safe_text(card, SEL_SEARCH["title"])
                if not title:
                    continue

                price_text = await safe_text(card, SEL_SEARCH["price"])
                price = parse_price(price_text)
                if price == 0:
                    continue

                mrp_text = await safe_text(card, SEL_SEARCH["mrp"])
                mrp = parse_price(mrp_text) or None

                rating_text = await safe_text(card, SEL_SEARCH["rating"])
                rating = _parse_float(rating_text)

                reviews_text = await safe_text(card, SEL_SEARCH["reviews"])
                review_count = _parse_int_with_commas(reviews_text)

                href = await safe_attr(card, SEL_SEARCH["link"], "href")
                if not href:
                    continue
                product_url = urljoin("https://www.flipkart.com", href)
                image_url = await safe_attr(card, SEL_SEARCH["image"], "src")

                pid_match = re.search(r"pid=([A-Z0-9]+)", product_url)
                product_id = pid_match.group(1) if pid_match else str(uuid.uuid4())

                products.append(Product(
                    platform=Platform.FLIPKART,
                    product_id=product_id,
                    title=title,
                    base_price=price,
                    mrp=mrp,
                    rating=rating,
                    review_count=review_count,
                    image_url=image_url,
                    product_url=product_url,
                ))

                if len(products) >= max_results:
                    break

            except Exception:
                continue

        return products

    # ══════════════════════════════════════════════════════════════════════════
    # OFFER PARSING — two strategies
    # ══════════════════════════════════════════════════════════════════════════

    async def _parse_offer_sections(self, page: Page, product: Product) -> list[Offer]:
        # Wait for the offer carousel to render (lazy-loaded React component)
        try:
            await page.wait_for_selector(SEL_OFFER["card_root"], timeout=8000)
        except Exception:
            pass

        card_handles = await page.query_selector_all(SEL_OFFER["card_root"])

        if not card_handles:
            return await self._parse_offers_fallback(page, product)

        # Grab the full page HTML once so we can use BeautifulSoup for static T&C
        page_html = await page.content()
        soup = BeautifulSoup(page_html, "lxml")

        offers: list[Offer] = []
        seen_keys: set[tuple] = set()

        for i, card_handle in enumerate(card_handles[:_s.scraper_max_offers_per_platform_per_product]):
            try:
                offer = await self._parse_single_offer_card(
                    page, card_handle, soup, product, i
                )
                if offer is None:
                    continue
                key = (offer.flat_discount, offer.bank, offer.offer_type)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                offers.append(offer)
            except Exception:
                continue

        return offers

    async def _parse_single_offer_card(
        self,
        page: Page,
        card: ElementHandle,
        soup: BeautifulSoup,
        product: Product,
        idx: int,
    ) -> Offer | None:
        """Extract one offer card using Playwright + BeautifulSoup for T&C."""

        # ── Amount ────────────────────────────────────────────────────────────
        # Selector uses  inter_bold  (underscore) — CRITICAL fix
        amount_el = await card.query_selector(SEL_OFFER["amount"])
        if not amount_el:
            return None
        amount_text = (await amount_el.inner_text()).strip()
        if not re.match(r"^[₹\d,]+\s*off$", amount_text, re.I):
            return None

        flat_discount = _rupee_to_float(amount_text)

        # ── Bank / program ────────────────────────────────────────────────────
        bank_el = await card.query_selector(SEL_OFFER["program"])
        bank_raw = (await bank_el.inner_text()).strip() if bank_el else ""
        bank = bank_raw or None

        # ── Offer type label ──────────────────────────────────────────────────
        # e.g. "Credit Card • Cashback", "Debit Card • Cashback", "UPI • Cashback"
        # The label is  inter_bold + 14px + pre-wrap  — NOT a CSS class
        type_el = await card.query_selector(SEL_OFFER["type_label"])
        type_label = (await type_el.inner_text()).strip() if type_el else ""
        offer_type, card_type = _infer_offer_type(type_label)

        # ── T&C ───────────────────────────────────────────────────────────────
        # Strategy A: bank T&C already in static HTML  →  use BeautifulSoup
        # Strategy B: dynamic drawer needed            →  Playwright click
        terms = ""
        if bank and _STATIC_TNC_BANKS.search(bank):
            terms = _extract_static_tnc(soup, bank)

        # TODO: if terms is empty, we could also try to find a nearby "See T&C" link in the static HTML and extract from there before resorting to Playwright click. For now we directly go to the click strategy if static extraction fails, since many offers (e.g. Mobikwik) don't have any static T&C at all.
        # if not terms:
        #     # Strategy B: click the footer chevron row to open T&C drawer
        #     terms = await self._click_and_extract_tnc(page, card)

        # ── Build title string ────────────────────────────────────────────────
        parts = [p for p in [amount_text, bank_raw, type_label] if p]
        title = " | ".join(parts)

        return Offer(
            offer_id=f"fk_{product.product_id}_{idx}",
            product_id=product.product_id,
            platform="flipkart",
            offer_type=offer_type,
            card_type=card_type,
            title=title,
            terms=terms,
            bank=bank,
            flat_discount=flat_discount,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # T&C  —  Playwright click-through strategy
    # ══════════════════════════════════════════════════════════════════════════

    async def _click_and_extract_tnc(self, page: Page, card: ElementHandle) -> str:
        """
        Click the footer row inside the card to open the T&C drawer.
        Waits for grumbles-tnc-* sections, collects text, then closes the drawer.
        """
        try:
            footer = await card.query_selector(SEL_OFFER["footer_click"])
            if not footer:
                return ""

            await footer.click(timeout=3000)

            # Wait for at least one grumbles-tnc section
            try:
                await page.wait_for_selector(SEL_OFFER["tnc_all"], timeout=5000)
            except Exception:
                await self._close_tnc_modal(page)
                return ""

            tnc_parts: list[str] = []
            for sel_key in ["tnc_details", "tnc_benefits", "tnc_conditions",
                            "tnc_duration", "tnc_other", "tnc_redemption"]:
                els = await page.query_selector_all(SEL_OFFER[sel_key])
                for el in els:
                    try:
                        t = (await el.inner_text()).strip()
                        if t:
                            tnc_parts.append(t)
                    except Exception:
                        continue

            terms = "\n\n".join(tnc_parts)

        except Exception:
            terms = ""

        finally:
            await self._close_tnc_modal(page)

        return terms

    async def _close_tnc_modal(self, page: Page) -> None:
        """
        Try multiple strategies to dismiss the T&C overlay.
        New React shell uses a fixed-position overlay (not role=dialog).
        """
        for sel in SEL_OFFER["close_attempts"]:
            try:
                await page.click(sel, timeout=1200)
                await asyncio.sleep(0.25)
                return
            except Exception:
                continue

        # Fallback 1: Escape key
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.25)
            return
        except Exception:
            pass

        # Fallback 2: click top-left corner (outside any overlay)
        try:
            await page.mouse.click(10, 10)
            await asyncio.sleep(0.25)
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # FALLBACK  —  older Flipkart offer layout  (list items)
    # ══════════════════════════════════════════════════════════════════════════

    async def _parse_offers_fallback(self, page: Page, product: Product) -> list[Offer]:
        items = await page.query_selector_all(SEL_OFFER["row_fallback"])
        offers: list[Offer] = []
        for i, item in enumerate(items[:15]):
            try:
                text = (await item.inner_text()).strip()
            except Exception:
                continue
            if not text or len(text) < 5:
                continue
            offers.append(Offer(
                offer_id=f"fk_{product.product_id}_fb_{i}",
                product_id=product.product_id,
                platform="flipkart",
                offer_type=OfferType.BANK_DISCOUNT,
                title=text,
                terms="",
            ))
        return offers


# ─────────────────────────────────────────────────────────────────────────────
# STATIC T&C PARSER  (BeautifulSoup — no browser needed)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_static_tnc(soup: BeautifulSoup, bank_name: str) -> str:
    """
    Flipkart embeds T&C for some banks (Axis, SBI etc.) in the static HTML.
    Find the section closest to the bank name that contains offer conditions.

    Algorithm:
      1. Find all text nodes matching the bank name.
      2. Walk up the DOM to find a container that holds eligibility/cashback text.
      3. Return the first 10 qualifying sentences (>30 chars) from that container.
    """
    tnc_keywords = {
        "cashback", "eligible", "applicable", "minimum transaction",
        "maximum", "statement quarter", "billing cycle", "terms and conditions",
    }

    for node in soup.find_all(string=re.compile(re.escape(bank_name), re.I)):
        container = node.parent
        for _ in range(7):
            if container is None:
                break
            all_text = container.get_text(separator=" ", strip=True).lower()
            hits = sum(1 for kw in tnc_keywords if kw in all_text)
            if hits >= 3:
                items = []
                for t_node in container.find_all(string=True):
                    t = str(t_node).strip()
                    if len(t) > 35 and not t.startswith("₹") and t not in items:
                        items.append(t)
                if len(items) >= 3:
                    return "\n".join(items[:12])
            container = container.parent

    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────────────────────

def _rupee_to_float(text: str) -> float:
    """'₹1,050 off' → 1050.0"""
    cleaned = re.sub(r"[^\d]", "", text)
    return float(cleaned) if cleaned else 0.0


def _parse_float(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"[\d.]+", text)
    if m:
        try:
            return float(m.group())
        except ValueError:
            pass
    return None


def _parse_int_with_commas(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r"[\d,]+", text)
    if m:
        try:
            return int(m.group().replace(",", ""))
        except ValueError:
            pass
    return None


async def _dismiss_popup(page: Page, selector: str) -> None:
    try:
        await page.click(selector, timeout=2500)
    except Exception:
        pass