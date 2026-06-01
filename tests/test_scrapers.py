"""
Scraper unit tests for AmazonScraper and FlipkartScraper.

Test strategy:
- Unit tests:       patch Playwright at the page/browser level — no real network
- Integration tests: marked @pytest.mark.integration — launch real browser, hit live sites
- All async tests run with pytest-asyncio (asyncio_mode = "auto")

Run unit tests only (fast, no network):
    uv run pytest tests/test_scrapers.py -m "not integration" -v

Run integration tests (slow, needs network + playwright chromium):
    uv run pytest tests/test_scrapers.py -m integration -v
"""
from __future__ import annotations

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.offer import Offer, OfferType
from models.product import Platform, Product
from scrapers.amazon import AmazonScraper
from scrapers.flipkart import FlipkartScraper
from scrapers.utils import parse_price

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_amazon_product() -> Product:
    return Product(
        platform=Platform.AMAZON,
        product_id="B0TEST1234",
        title="Test Phone Amazon",
        base_price=22999.0,
        mrp=27999.0,
        rating=4.3,
        review_count=12345,
        image_url="https://m.media-amazon.com/images/test.jpg",
        product_url="https://www.amazon.in/dp/B0TEST1234",
    )


@pytest.fixture
def sample_flipkart_product() -> Product:
    return Product(
        platform=Platform.FLIPKART,
        product_id="MOBTEST1234",
        title="Test Phone Flipkart",
        base_price=21999.0,
        mrp=26999.0,
        rating=4.1,
        review_count=8450,
        image_url="https://rukminim1.flixcart.com/test.jpg",
        product_url="https://www.flipkart.com/test-phone/p/itm?pid=MOBTEST1234",
    )


def _make_card_el(title: str, href: str = "/test-phone/p/itm?pid=ABC123") -> AsyncMock:
    """Helper: create a mock Playwright element mimicking a product card."""
    el = AsyncMock()

    async def query_selector(selector: str) -> AsyncMock | None:
        found = AsyncMock()
        found.inner_text = AsyncMock(return_value=title)
        found.get_attribute = AsyncMock(return_value=href)
        return found

    el.query_selector = query_selector
    el.inner_text = AsyncMock(return_value=title)
    return el


# ─────────────────────────────────────────────────────────────────────────────
# parse_price utility
# ─────────────────────────────────────────────────────────────────────────────

class TestParsePrice:
    def test_indian_format_with_rupee(self):
        assert parse_price("₹22,999") == 22999.0

    def test_plain_number(self):
        assert parse_price("21999") == 21999.0

    def test_price_with_decimal(self):
        assert parse_price("₹1,499.99") == 1499.99

    def test_empty_string(self):
        assert parse_price("") == 0.0

    def test_none_input(self):
        assert parse_price(None) == 0.0

    def test_price_with_spaces(self):
        assert parse_price("  ₹ 14,999  ") == 14999.0

    def test_lakhs_format(self):
        assert parse_price("₹1,00,000") == 100000.0

    def test_invalid_text(self):
        assert parse_price("Not available") == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Product model
# ─────────────────────────────────────────────────────────────────────────────

class TestProductModel:
    def test_discount_pct_calculated(self, sample_amazon_product):
        p = sample_amazon_product
        expected = round((27999 - 22999) / 27999 * 100, 1)
        assert p.discount_pct == expected

    def test_discount_pct_none_when_no_mrp(self):
        p = Product(
            platform=Platform.AMAZON,
            product_id="X1",
            title="Test",
            base_price=10000.0,
            product_url="https://amazon.in/dp/X1",
        )
        assert p.discount_pct is None

    def test_discount_pct_none_when_mrp_less_than_price(self):
        p = Product(
            platform=Platform.FLIPKART,
            product_id="X2",
            title="Test",
            base_price=10000.0,
            mrp=9999.0,
            product_url="https://flipkart.com/p/X2",
        )
        assert p.discount_pct is None

    def test_platform_enum_values(self):
        assert Platform.AMAZON == "amazon"
        assert Platform.FLIPKART == "flipkart"

    def test_product_in_stock_default(self, sample_amazon_product):
        assert sample_amazon_product.in_stock is True


# ─────────────────────────────────────────────────────────────────────────────
# Offer model
# ─────────────────────────────────────────────────────────────────────────────

class TestOfferModel:
    def _make_offer(self, **kwargs) -> Offer:
        defaults = dict(
            offer_id="o1",
            product_id="p1",
            platform="amazon",
            offer_type=OfferType.BANK_DISCOUNT,
            title="10% off with HDFC",
        )
        defaults.update(kwargs)
        return Offer(**defaults)

    def test_discount_amount_percentage(self):
        from backend.models.offer import DiscountType
        offer = self._make_offer(
            discount_type=DiscountType.PERCENTAGE,
            discount_value=10.0,
        )
        assert offer.discount_amount(20000) == 2000.0

    def test_discount_amount_flat(self):
        from backend.models.offer import DiscountType
        offer = self._make_offer(
            discount_type=DiscountType.FLAT,
            discount_value=1500.0,
        )
        assert offer.discount_amount(20000) == 1500.0

    def test_discount_amount_respects_cap(self):
        from backend.models.offer import DiscountType
        offer = self._make_offer(
            discount_type=DiscountType.PERCENTAGE,
            discount_value=10.0,
            max_discount_cap=1500.0,
        )
        assert offer.discount_amount(20000) == 1500.0

    def test_discount_zero_when_min_order_not_met(self):
        from backend.models.offer import DiscountType
        offer = self._make_offer(
            discount_type=DiscountType.FLAT,
            discount_value=1000.0,
            min_order_value=15000.0,
        )
        assert offer.discount_amount(10000) == 0.0

    def test_applies_to_card_matching_bank(self):
        from backend.models.offer import CardType
        offer = self._make_offer(bank="HDFC", card_type=CardType.CREDIT)
        assert offer.applies_to_card("HDFC", CardType.CREDIT) is True

    def test_applies_to_card_wrong_bank(self):
        from backend.models.offer import CardType
        offer = self._make_offer(bank="HDFC", card_type=CardType.CREDIT)
        assert offer.applies_to_card("SBI", CardType.CREDIT) is False

    def test_applies_to_card_type_mismatch(self):
        from backend.models.offer import CardType
        offer = self._make_offer(bank="HDFC", card_type=CardType.CREDIT)
        assert offer.applies_to_card("HDFC", CardType.DEBIT) is False

    def test_applies_to_card_all_card_type(self):
        from backend.models.offer import CardType
        offer = self._make_offer(bank="HDFC", card_type=CardType.ALL)
        assert offer.applies_to_card("HDFC", CardType.CREDIT) is True
        assert offer.applies_to_card("HDFC", CardType.DEBIT) is True


# ─────────────────────────────────────────────────────────────────────────────
# AmazonScraper — unit tests (mocked Playwright)
# ─────────────────────────────────────────────────────────────────────────────

class TestAmazonScraperUnit:
    """Tests that mock Playwright — no real network, runs in <1s."""

    def _build_mock_page(self, cards: list) -> AsyncMock:
        page = AsyncMock()
        page.goto = AsyncMock(return_value=None)
        page.query_selector_all = AsyncMock(return_value=cards)
        return page

    def _build_mock_card(
        self,
        title="Test Phone",
        price="₹22,999",
        mrp="₹27,999",
        rating="4.3 out of 5 stars",
        reviews="12,345 ratings",
        href="/dp/B0TESTABCD",
        img="https://img.amazon.in/test.jpg",
    ) -> AsyncMock:
        card = AsyncMock()

        async def qs(selector):
            mock_el = AsyncMock()
            if "h2 a span" in selector or "a-icon-alt" in selector:
                mock_el.inner_text = AsyncMock(return_value=title if "span" in selector else rating)
                mock_el.get_attribute = AsyncMock(return_value=href)
            elif "price-whole" in selector:
                mock_el.inner_text = AsyncMock(return_value=price)
            elif "a-text-price" in selector or "offscreen" in selector:
                mock_el.inner_text = AsyncMock(return_value=mrp)
            elif "ratings" in selector or "underline" in selector:
                mock_el.inner_text = AsyncMock(return_value=reviews)
            elif "s-image" in selector:
                mock_el.get_attribute = AsyncMock(return_value=img)
                mock_el.inner_text = AsyncMock(return_value="")
            else:
                mock_el.inner_text = AsyncMock(return_value="")
                mock_el.get_attribute = AsyncMock(return_value="")
            return mock_el

        card.query_selector = qs
        card.get_attribute = AsyncMock(return_value=href)
        return card

    async def test_search_products_returns_list(self, sample_amazon_product):
        scraper = AmazonScraper()
        mock_card = self._build_mock_card()
        mock_page = self._build_mock_page([mock_card])
        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()
        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw.__aexit__ = AsyncMock(return_value=None)
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

        with patch("backend.scrapers.amazon.async_playwright", return_value=mock_pw), \
             patch("backend.scrapers.amazon.random_delay", new_callable=AsyncMock), \
             patch("backend.scrapers.amazon.random_ua", return_value="Mozilla/5.0"):
            result = await scraper._parse_search_page(mock_page, max_results=5)

        assert isinstance(result, list)

    async def test_scraper_respects_max_results(self):
        scraper = AmazonScraper()
        cards = [self._build_mock_card(title=f"Phone {i}") for i in range(20)]
        mock_page = self._build_mock_page(cards)

        with patch("backend.scrapers.amazon.random_delay", new_callable=AsyncMock), \
             patch("backend.scrapers.amazon.random_ua", return_value="Mozilla/5.0"):
            result = await scraper._parse_search_page(mock_page, max_results=5)

        assert len(result) <= 5

    async def test_scrape_offers_returns_list(self, sample_amazon_product):
        scraper = AmazonScraper()
        mock_item = AsyncMock()
        mock_item.inner_text = AsyncMock(return_value="10% instant discount with HDFC Bank Credit Cards")
        mock_terms_el = AsyncMock()
        mock_terms_el.inner_text = AsyncMock(return_value="Minimum transaction value ₹5000")
        mock_item.query_selector = AsyncMock(return_value=mock_terms_el)

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[mock_item, mock_item])

        mock_browser = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)
        mock_browser.close = AsyncMock()
        mock_pw = AsyncMock()
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw.__aexit__ = AsyncMock(return_value=None)
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

        with patch("backend.scrapers.amazon.async_playwright", return_value=mock_pw), \
             patch("backend.scrapers.amazon.random_delay", new_callable=AsyncMock), \
             patch("backend.scrapers.amazon.random_ua", return_value="Mozilla/5.0"):
            offers = await scraper._parse_offer_sections(mock_page, sample_amazon_product)

        assert isinstance(offers, list)
        for offer in offers:
            assert isinstance(offer, Offer)
            assert offer.platform == "amazon"
            assert offer.product_id == sample_amazon_product.product_id
            assert len(offer.title) > 0

    async def test_scrape_offers_empty_on_no_items(self, sample_amazon_product):
        scraper = AmazonScraper()
        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[])

        with patch("backend.scrapers.amazon.random_delay", new_callable=AsyncMock), \
             patch("backend.scrapers.amazon.random_ua", return_value="Mozilla/5.0"):
            offers = await scraper._parse_offer_sections(mock_page, sample_amazon_product)

        assert offers == []

    async def test_offer_fields_populated(self, sample_amazon_product):
        scraper = AmazonScraper()
        mock_item = AsyncMock()
        mock_item.inner_text = AsyncMock(return_value="5% cashback with SBI Credit Card")
        mock_item.query_selector = AsyncMock(return_value=None)

        mock_page = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[mock_item])

        with patch("backend.scrapers.amazon.random_delay", new_callable=AsyncMock):
            offers = await scraper._parse_offer_sections(mock_page, sample_amazon_product)

        if offers:
            assert offers[0].offer_type == OfferType.BANK_DISCOUNT
            assert offers[0].platform == "amazon"


# ─────────────────────────────────────────────────────────────────────────────
# FlipkartScraper — unit tests (mocked Playwright)
# ─────────────────────────────────────────────────────────────────────────────

class TestFlipkartScraperUnit:
    """Tests that mock Playwright — no real network, runs in <1s."""

    def _build_mock_card(
        self,
        title="Test Flipkart Phone",
        price="₹21,999",
        mrp="₹26,999",
        rating="4.1",
        reviews="8,450 Ratings",
        href="/test-phone/p/itm?pid=MOBTEST1234",
        img="https://rukminim1.flixcart.com/test.jpg",
    ) -> AsyncMock:
        card = AsyncMock()

        async def qs(selector):
            mock_el = AsyncMock()
            if "KzDlHZ" in selector or "WKTcLC" in selector or "_4rR01T" in selector:
                mock_el.inner_text = AsyncMock(return_value=title)
            elif "Nx9bqj" in selector or "_30jeq3" in selector:
                mock_el.inner_text = AsyncMock(return_value=price)
            elif "yRaY8j" in selector or "_3I9_wc" in selector:
                mock_el.inner_text = AsyncMock(return_value=mrp)
            elif "XQDdHH" in selector or "_1lRcqv" in selector:
                mock_el.inner_text = AsyncMock(return_value=rating)
            elif "Wphh3N" in selector or "_13vcmD" in selector:
                mock_el.inner_text = AsyncMock(return_value=reviews)
            elif "CGtC98" in selector or "s1Q9rs" in selector or "_1fQZEK" in selector:
                mock_el.get_attribute = AsyncMock(return_value=href)
                mock_el.inner_text = AsyncMock(return_value="")
            elif "DByuf4" in selector or "_396cs4" in selector:
                mock_el.get_attribute = AsyncMock(return_value=img)
                mock_el.inner_text = AsyncMock(return_value="")
            else:
                mock_el.inner_text = AsyncMock(return_value="")
                mock_el.get_attribute = AsyncMock(return_value="")
            return mock_el

        card.query_selector = qs
        card.get_attribute = AsyncMock(return_value=href)
        return card

    async def test_parse_search_page_returns_list(self):
        scraper = FlipkartScraper()
        card = self._build_mock_card()
        mock_page = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[card])

        with patch("backend.scrapers.flipkart.random_delay", new_callable=AsyncMock), \
             patch("backend.scrapers.flipkart.random_ua", return_value="Mozilla/5.0"):
            result = await scraper._parse_search_page(mock_page, max_results=5)

        assert isinstance(result, list)

    async def test_parse_search_page_respects_max_results(self):
        scraper = FlipkartScraper()
        cards = [self._build_mock_card(title=f"Phone {i}") for i in range(20)]
        mock_page = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=cards)

        with patch("backend.scrapers.flipkart.random_delay", new_callable=AsyncMock):
            result = await scraper._parse_search_page(mock_page, max_results=7)

        assert len(result) <= 7

    async def test_product_has_required_fields(self):
        scraper = FlipkartScraper()
        card = self._build_mock_card()
        mock_page = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[card])

        with patch("backend.scrapers.flipkart.random_delay", new_callable=AsyncMock), \
             patch("backend.scrapers.flipkart.random_ua", return_value="Mozilla/5.0"):
            result = await scraper._parse_search_page(mock_page, max_results=5)

        if result:
            p = result[0]
            assert isinstance(p, Product)
            assert p.platform == Platform.FLIPKART
            assert len(p.title) > 0
            assert p.base_price > 0
            assert p.product_url.startswith("https://www.flipkart.com")

    async def test_scrape_offers_returns_offers(self, sample_flipkart_product):
        scraper = FlipkartScraper()

        mock_item = AsyncMock()
        mock_item.inner_text = AsyncMock(return_value="₹1500 off on HDFC Bank Credit Card transactions")
        mock_terms_el = AsyncMock()
        mock_terms_el.inner_text = AsyncMock(return_value="Min transaction ₹10,000")
        mock_item.query_selector = AsyncMock(return_value=mock_terms_el)

        mock_page = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[mock_item])

        with patch("backend.scrapers.flipkart.random_delay", new_callable=AsyncMock), \
             patch("backend.scrapers.flipkart.random_ua", return_value="Mozilla/5.0"):
            offers = await scraper._parse_offer_sections(mock_page, sample_flipkart_product)

        assert isinstance(offers, list)
        for o in offers:
            assert isinstance(o, Offer)
            assert o.platform == "flipkart"
            assert o.product_id == sample_flipkart_product.product_id

    async def test_scrape_offers_skips_short_text(self, sample_flipkart_product):
        scraper = FlipkartScraper()

        short_item = AsyncMock()
        short_item.inner_text = AsyncMock(return_value="ok")  # less than 5 chars
        valid_item = AsyncMock()
        valid_item.inner_text = AsyncMock(return_value="10% off with Axis Bank Credit Card")
        valid_item.query_selector = AsyncMock(return_value=None)

        mock_page = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[short_item, valid_item])

        with patch("backend.scrapers.flipkart.random_delay", new_callable=AsyncMock):
            offers = await scraper._parse_offer_sections(mock_page, sample_flipkart_product)

        titles = [o.title for o in offers]
        assert not any(len(t) < 5 for t in titles)

    async def test_dismiss_login_popup_no_error(self):
        scraper = FlipkartScraper()
        mock_page = AsyncMock()
        mock_page.click = AsyncMock(side_effect=Exception("Element not found"))
        # should silently pass without raising
        await scraper._dismiss_login(mock_page)

    async def test_offer_id_format(self, sample_flipkart_product):
        scraper = FlipkartScraper()
        mock_item = AsyncMock()
        mock_item.inner_text = AsyncMock(return_value="₹2000 off with SBI Bank Credit Card")
        mock_item.query_selector = AsyncMock(return_value=None)

        mock_page = AsyncMock()
        mock_page.query_selector_all = AsyncMock(return_value=[mock_item])

        with patch("backend.scrapers.flipkart.random_delay", new_callable=AsyncMock):
            offers = await scraper._parse_offer_sections(mock_page, sample_flipkart_product)

        if offers:
            assert offers[0].offer_id.startswith("fk_")
            assert sample_flipkart_product.product_id in offers[0].offer_id


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests — real browser, real network
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_flipkart_search_real_network():
    """
    Live Flipkart search — requires network + playwright chromium installed.
    Run: uv run pytest tests/test_scrapers.py::test_flipkart_search_real_network -v
    """
    scraper = FlipkartScraper()
    products = await scraper.search_products(
        query="mobile phone",
        price_min=15000,
        price_max=25000,
        max_results=5,
    )
    print("Testing for mobile phones between ₹15,000 and ₹25,000 on Flipkart with max 5 results...")
    print("Test Flipkart internet Search - Products found:", products)
    assert isinstance(products, list)
    assert len(products) > 0
    for p in products:
        assert p.platform == Platform.FLIPKART
        assert p.base_price > 0
        assert 12000 <= p.base_price <= 28000
        assert len(p.title) > 0
        assert p.product_url.startswith("https://www.flipkart.com")


@pytest.mark.integration
async def test_amazon_search_real_network():
    """
    Live Amazon search — requires network + playwright chromium installed.
    Run: uv run pytest tests/test_scrapers.py::test_amazon_search_real_network -v
    """
    scraper = AmazonScraper()
    products = await scraper.search_products(
        query="mobile phone",
        price_min=15000,
        price_max=25000,
        max_results=5,
    )
    assert isinstance(products, list)
    assert len(products) > 0
    for p in products:
        assert p.platform == Platform.AMAZON
        assert p.base_price > 0
        assert len(p.title) > 0
        assert "amazon.in" in p.product_url
    print("Testing for mobile phones between ₹15,000 and ₹25,000 on Amazon India with max 5 results...")
    print("Test Amazon internet Search - Products found:", products)

@pytest.mark.integration
async def test_flipkart_offer_scrape_real_network(sample_flipkart_product):
    """
    Live Flipkart offer scrape for a known product URL.
    """
    product = Product(
        platform=Platform.FLIPKART,
        product_id="MOBGTAGHYHFPZWJ6",
        title="Samsung Galaxy M35",
        base_price=19999.0,
        product_url="https://www.flipkart.com/samsung-galaxy-m35-5g-thunder-grey-128-gb/p/itmf9e1bc9bb1c3b",
    )
    scraper = FlipkartScraper()
    offers = await scraper.scrape_offers(product)
    assert isinstance(offers, list)
    for o in offers:
        assert isinstance(o, Offer)
        assert len(o.title) > 4
    print("Testing offer scrape for Samsung Galaxy M35 on Flipkart...")
    print("Test Flipkart internet Offer Scrape - Offers found:", offers)


@pytest.mark.integration
async def test_amazon_offer_scrape_real_network():
    """
    Live Amazon offer scrape for a known product URL.
    """
    product = Product(
        platform=Platform.AMAZON,
        product_id="B0CHX2F5QT",
        title="Samsung Galaxy M35",
        base_price=19999.0,
        product_url="https://www.amazon.in/dp/B0CHX2F5QT",
    )
    scraper = AmazonScraper()
    offers = await scraper.scrape_offers(product)
    assert isinstance(offers, list)
    for o in offers:
        assert isinstance(o, Offer)
        assert len(o.title) > 4
    print("Testing offer scrape for Samsung Galaxy M35 on Amazon India...")
    print("Test Amazon internet Offer Scrape - Offers found:", offers)
